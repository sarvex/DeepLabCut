#
# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import functools
import os
import re
import tensorflow as tf

import deeplabcut.pose_estimation_tensorflow.backbones.efficientnet_model as efficientnet_model
import deeplabcut.pose_estimation_tensorflow.nnets.utils as utils

MEAN_RGB = [0.485 * 255, 0.456 * 255, 0.406 * 255]
STDDEV_RGB = [0.229 * 255, 0.224 * 255, 0.225 * 255]


def efficientnet_params(model_name):
    """Get efficientnet params based on model name."""
    params_dict = {
        # (width_coefficient, depth_coefficient, resolution, dropout_rate)
        "efficientnet-b0": (1.0, 1.0, 224, 0.2),
        "efficientnet-b1": (1.0, 1.1, 240, 0.2),
        "efficientnet-b2": (1.1, 1.2, 260, 0.3),
        "efficientnet-b3": (1.2, 1.4, 300, 0.3),
        "efficientnet-b4": (1.4, 1.8, 380, 0.4),
        "efficientnet-b5": (1.6, 2.2, 456, 0.4),
        "efficientnet-b6": (1.8, 2.6, 528, 0.5),
        "efficientnet-b7": (2.0, 3.1, 600, 0.5),
    }
    return params_dict[model_name]


class BlockDecoder(object):
    """Block Decoder for readability."""

    def _decode_block_string(self, block_string):
        """Gets a block through a string notation of arguments."""
        assert isinstance(block_string, str)
        ops = block_string.split("_")
        options = {}
        for op in ops:
            splits = re.split(r"(\d.*)", op)
            if len(splits) >= 2:
                key, value = splits[:2]
                options[key] = value

        if "s" not in options or len(options["s"]) != 2:
            raise ValueError("Strides options should be a pair of integers.")

        return efficientnet_model.BlockArgs(
            kernel_size=int(options["k"]),
            num_repeat=int(options["r"]),
            input_filters=int(options["i"]),
            output_filters=int(options["o"]),
            expand_ratio=int(options["e"]),
            id_skip=("noskip" not in block_string),
            se_ratio=float(options["se"]) if "se" in options else None,
            strides=[int(options["s"][0]), int(options["s"][1])],
            conv_type=int(options["c"]) if "c" in options else 0,
        )

    def _encode_block_string(self, block):
        """Encodes a block to a string."""
        args = [
            "r%d" % block.num_repeat,
            "k%d" % block.kernel_size,
            "s%d%d" % (block.strides[0], block.strides[1]),
            f"e{block.expand_ratio}",
            "i%d" % block.input_filters,
            "o%d" % block.output_filters,
            "c%d" % block.conv_type,
        ]
        if block.se_ratio > 0 and block.se_ratio <= 1:
            args.append(f"se{block.se_ratio}")
        if block.id_skip is False:
            args.append("noskip")
        return "_".join(args)

    def decode(self, string_list):
        """Decodes a list of string notations to specify blocks inside the network.
        Args:
          string_list: a list of strings, each string is a notation of block.
        Returns:
          A list of namedtuples to represent blocks arguments.
        """
        assert isinstance(string_list, list)
        return [
            self._decode_block_string(block_string) for block_string in string_list
        ]

    def encode(self, blocks_args):
        """Encodes a list of Blocks to a list of strings.
        Args:
          blocks_args: A list of namedtuples to represent blocks arguments.
        Returns:
          a list of strings, each string is a notation of block.
        """
        return [self._encode_block_string(block) for block in blocks_args]


def swish(features, use_native=True):
    """Computes the Swish activation function.
    The tf.nn.swish operation uses a custom gradient to reduce memory usage.
    Since saving custom gradients in SavedModel is currently not supported, and
    one would not be able to use an exported TF-Hub module for fine-tuning, we
    provide this wrapper that can allow to select whether to use the native
    TensorFlow swish operation, or whether to use a customized operation that
    has uses default TensorFlow gradient computation.
    Args:
      features: A `Tensor` representing preactivation values.
      use_native: Whether to use the native swish from tf.nn that uses a custom
        gradient to reduce memory usage, or to use customized swish that uses
        default TensorFlow gradient computation.
    Returns:
      The activation value.
    """
    if use_native:
        return tf.nn.swish(features)
    features = tf.convert_to_tensor(value=features, name="features")
    return features * tf.nn.sigmoid(features)


def efficientnet(
    width_coefficient=None,
    depth_coefficient=None,
    dropout_rate=0.2,
    drop_connect_rate=0.2,
):
    """Creates a efficientnet model."""
    blocks_args = [
        "r1_k3_s11_e1_i32_o16_se0.25",
        "r2_k3_s22_e6_i16_o24_se0.25",
        "r2_k5_s22_e6_i24_o40_se0.25",
        "r3_k3_s22_e6_i40_o80_se0.25",
        "r3_k5_s11_e6_i80_o112_se0.25",
        "r4_k5_s11_e6_i112_o192_se0.25",
        "r1_k3_s11_e6_i192_o320_se0.25",
    ]
    # blocks_args = [
    #     'r1_k3_s11_e1_i32_o16_se0.25', 'r2_k3_s22_e6_i16_o24_se0.25',
    #     'r2_k5_s22_e6_i24_o40_se0.25', 'r3_k3_s22_e6_i40_o80_se0.25',
    #     'r3_k5_s11_e6_i80_o112_se0.25', 'r4_k5_s22_e6_i112_o192_se0.25',
    #     'r1_k3_s11_e6_i192_o320_se0.25',
    # ]
    global_params = efficientnet_model.GlobalParams(
        batch_norm_momentum=0.99,
        batch_norm_epsilon=1e-3,
        dropout_rate=dropout_rate,
        drop_connect_rate=drop_connect_rate,
        data_format="channels_last",
        num_classes=1000,
        width_coefficient=width_coefficient,
        depth_coefficient=depth_coefficient,
        depth_divisor=8,
        min_depth=None,
        relu_fn=tf.nn.swish,
        # The default is TPU-specific batch norm.
        # The alternative is tf.layers.BatchNormalization.
        # batch_norm=utils.TpuBatchNormalization,  # TPU-specific requirement.
        batch_norm=utils.BatchNormalization,
        use_se=True,
    )
    decoder = BlockDecoder()
    return decoder.decode(blocks_args), global_params


def get_model_params(model_name, override_params):
    """Get the block args and global params for a given model."""
    if not model_name.startswith("efficientnet"):
        raise NotImplementedError(f"model name is not pre-defined: {model_name}")

    width_coefficient, depth_coefficient, _, dropout_rate = efficientnet_params(
        model_name
    )
    blocks_args, global_params = efficientnet(
        width_coefficient, depth_coefficient, dropout_rate
    )
    if override_params:
        # ValueError will be raised here if override_params has fields not included
        # in global_params.
        global_params = global_params._replace(**override_params)

    tf.compat.v1.logging.info("global_params= %s", global_params)
    tf.compat.v1.logging.info("blocks_args= %s", blocks_args)
    return blocks_args, global_params


def build_model(
    images,
    model_name,
    training,
    override_params=None,
    model_dir=None,
    fine_tuning=False,
    features_only=False,
):
    """A helper function to creates a model and returns predicted logits.
    Args:
      images: input images tensor.
      model_name: string, the predefined model name.
      training: boolean, whether the model is constructed for training.
      override_params: A dictionary of params for overriding. Fields must exist in
        efficientnet_model.GlobalParams.
      model_dir: string, optional model dir for saving configs.
      fine_tuning: boolean, whether the model is used for finetuning.
      features_only: build the base feature network only.
    Returns:
      logits: the logits tensor of classes.
      endpoints: the endpoints for each layer.
    Raises:
      When model_name specified an undefined model, raises NotImplementedError.
      When override_params has invalid fields, raises ValueError.
    """
    assert isinstance(images, tf.Tensor)
    if not training or fine_tuning:
        if not override_params:
            override_params = {}
        override_params["batch_norm"] = utils.BatchNormalization
        override_params["relu_fn"] = functools.partial(swish, use_native=False)
    blocks_args, global_params = get_model_params(model_name, override_params)

    if model_dir:
        param_file = os.path.join(model_dir, "model_params.txt")
        if not tf.io.gfile.exists(param_file):
            if not tf.io.gfile.exists(model_dir):
                tf.io.gfile.makedirs(model_dir)
            with tf.io.gfile.GFile(param_file, "w") as f:
                tf.compat.v1.logging.info(f"writing to {param_file}")
                f.write("model_name= %s\n\n" % model_name)
                f.write("global_params= %s\n\n" % str(global_params))
                f.write("blocks_args= %s\n\n" % str(blocks_args))

    with tf.compat.v1.variable_scope(model_name):
        model = efficientnet_model.Model(blocks_args, global_params)
        outputs = model(images, training=training, features_only=features_only)
    outputs = tf.identity(outputs, "features" if features_only else "logits")
    return outputs, model.endpoints


def build_model_base(
    images, model_name, use_batch_norm=False, drop_out=False, override_params=None
):
    """A helper function to create a base model and return global_pool.
    Args:
      images: input images tensor.
      model_name: string, the predefined model name.
      training: boolean, whether the model is constructed for training.
      override_params: A dictionary of params for overriding. Fields must exist in
        efficientnet_model.GlobalParams.
    Returns:
      features: global pool features.
      endpoints: the endpoints for each layer.
    Raises:
      When model_name specified an undefined model, raises NotImplementedError.
      When override_params has invalid fields, raises ValueError.
    """
    assert isinstance(images, tf.Tensor)
    blocks_args, global_params = get_model_params(model_name, override_params)

    with tf.compat.v1.variable_scope(model_name):
        model = efficientnet_model.Model(blocks_args, global_params)
        features = model(
            images, use_batch_norm=use_batch_norm, drop_out=drop_out, features_only=True
        )

    features = tf.identity(features, "features")
    return features, model.endpoints
