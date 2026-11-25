import os
import re
import platform
import subprocess

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog
from PySide6.QtWidgets import QMainWindow, QMessageBox

from UIFileDialogView import Ui_Dialog
from UIFunc import scripts, scripts_map

from 点巡 import to_abs_path


class FileDialog(Ui_Dialog):
    def __init__(self):
        self.dialog = QDialog()
        self.setupUi(self.dialog)
        self.dialog.setFixedSize(self.dialog.width(), self.dialog.height())
        self.choice.clicked.connect(self.choice_file)
        self.edit.clicked.connect(self.edit_file)
        self.rename.clicked.connect(lambda: self.rename_file(self.lineEdit.text()))

        self.main_window = QMainWindow()
        self.filename = scripts[scripts_map['current_index']]
        self.lineEdit.setText(self.filename)
        self.path = os.path.join(to_abs_path("scripts"))
        
        self.dialog.setWindowTitle('脚本管理')
        self.file_name.setText('脚本文件')
        self.choice.setText('选择')
        self.edit.setText('编辑')
        self.rename.setText('重命名')
    

    def choice_file(self):
        file = QFileDialog.getOpenFileName(self.main_window, "选择文件", dir=to_abs_path('scripts'), filter='*.txt *.json5')[0]
        file_name = re.split(r'\\|\/', file)[-1]
        if file_name != '':
            scripts_map['current_index'] = scripts_map[file_name]
            if file_name.strip() != '' and file_name is not None:
                self.lineEdit.setText(file_name)


    def edit_file(self):
        user_platform = platform.system()
        try:
            if user_platform == 'Linux':
                subprocess.call(['xdg-open', os.path.join(self.path, self.lineEdit.text())])
            elif user_platform == 'Darwin':
                # mac
                subprocess.call(['open', os.path.join(self.path, self.lineEdit.text())])
            else:
                os.startfile(os.path.join(self.path, self.lineEdit.text()))
        except FileNotFoundError:
            QMessageBox().warning(self.main_window, "提示", "文件不存在")
            self.lineEdit.setText('')


    def rename_file(self, filename):
        new_file_name = str(QInputDialog.getText(self.main_window, 
                                                 '重命名脚本',
                                                 '请输入新的文件名：')[0])

        if new_file_name != None and new_file_name.strip() != '':
            if filename.endswith('.txt'):
                if not new_file_name.endswith('.txt'):
                    new_file_name = new_file_name + '.txt'
            elif filename.endswith('.json5'):
                if not new_file_name.endswith('.json5'):
                    new_file_name = new_file_name + '.json5'

            try:
                os.rename(os.path.join(self.path, self.lineEdit.text()), os.path.join(self.path, new_file_name))
                QMessageBox().information(self.main_window, '提示', '重命名成功')
                # 更新
                filename = self.lineEdit.text()
                index = scripts_map.get(filename)
                scripts_map.pop(filename)
                scripts_map[new_file_name] = index
                scripts[index] = new_file_name
                self.lineEdit.setText(new_file_name)
            except FileNotFoundError:
                QMessageBox.warning(self.main_window, '提示', '文件不存在')
        else:
            QMessageBox.warning(self.main_window, '提示', '文件名不能为空')


    def show(self):
        self.dialog.show()
        self.dialog.exec_()
        
