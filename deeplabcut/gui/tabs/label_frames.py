#
# DeepLabCut Toolbox (deeplabcut.org)
# © A. & M.W. Mathis Labs
# https://github.com/DeepLabCut/DeepLabCut
#
# Please see AUTHORS for contributors.
# https://github.com/DeepLabCut/DeepLabCut/blob/master/AUTHORS
#
# Licensed under GNU Lesser General Public License v3.0
#
import os
from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from deeplabcut.generate_training_dataset import check_labels
from deeplabcut.gui.components import DefaultTab
from deeplabcut.gui.widgets import launch_napari


def label_frames(config_path):
    _ = launch_napari(config_path)


refine_labels = label_frames


class LabelFrames(DefaultTab):
    def __init__(self, root, parent, h1_description):
        super(LabelFrames, self).__init__(root, parent, h1_description)

        self._set_page()

    def _set_page(self):
        self.label_frames_btn = QtWidgets.QPushButton("Label Frames")
        self.label_frames_btn.clicked.connect(self.label_frames)
        self.check_labels_btn = QtWidgets.QPushButton("Check Labels")
        self.check_labels_btn.clicked.connect(self.check_labels)
        self.main_layout.addWidget(self.label_frames_btn, alignment=Qt.AlignLeft)
        self.main_layout.addWidget(self.check_labels_btn, alignment=Qt.AlignLeft)

    def log_color_by_option(self, choice):
        self.root.logger.info(f"Labeled images will by colored by {choice.upper()}")

    def label_frames(self):
        dialog = QtWidgets.QFileDialog(self)
        dialog.setFileMode(QtWidgets.QFileDialog.Directory)
        dialog.setViewMode(QtWidgets.QFileDialog.Detail)
        dialog.setDirectory(
            os.path.join(os.path.dirname(self.root.config), "labeled-data")
        )
        if dialog.exec_():
            folder = dialog.selectedFiles()[0]
            has_h5 = any(file.endswith(".h5") for file in os.listdir(folder))
            if not has_h5:
                folder = [folder, self.root.config]
            _ = launch_napari(folder)

    def check_labels(self):
        check_labels(self.root.config, visualizeindividuals=self.root.is_multianimal)
