import os
import sys
import math
import logging
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget, QSpinBox
from PySide6.QtCore import Qt, Slot, QRect

import UIFunc
import Recorder
import argparse
from Event import ScriptEvent
from loguru import logger

from Plugin.Manager import PluginManager
from Util.RunScriptClass import RunScriptCMDClass, StopFlag


def to_abs_path(*args):
    root = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
    return os.path.join(root, *args)


def resize_layout(ui, ratio_w, ratio_h):
    ui.resize(ui.width() * ratio_w, ui.height() * ratio_h)

    for q_widget in ui.findChildren(QWidget):
        q_widget.setGeometry(QRect(q_widget.x() * ratio_w,
                                   q_widget.y() * ratio_h,
                                   q_widget.width() * ratio_w,
                                   q_widget.height() * ratio_h))
        q_widget.setStyleSheet('font-size: ' + str(
                                math.ceil(9 * min(ratio_h, ratio_w))) + 'px')
        if isinstance(q_widget, QSpinBox):
            q_widget.setStyleSheet('padding-left: 7px')


def main():
    if getattr(sys, 'frozen', False):
        local_app_data = os.environ.get('LOCALAPPDATA', str(Path.home()))
        data_dir = Path(local_app_data) / '点巡'
        data_dir.mkdir(parents=True, exist_ok=True)
        log_dir = data_dir / 'logs'
        log_dir.mkdir(exist_ok=True)
        logging.basicConfig(filename=log_dir / 'startup.log', level=logging.INFO,
                            format='%(asctime)s %(levelname)s %(message)s')
        try:
            return _main(data_dir)
        except Exception:
            logging.exception('Application startup failed')
            import traceback
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(None, '点巡 启动失败',
                                 f'详细错误已保存到 {log_dir / "startup.log"}\n\n{traceback.format_exc()[-3000:]}')
            return 1
    return _main()


def _main(data_dir=None):
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    ui = UIFunc.UIFunc(app, data_dir=data_dir)

    ui.show()
    return app.exec()


@logger.catch
def single_run(script_path, run_times):
    flag = StopFlag(False)
    thread = RunScriptCMDClass(script_path, run_times, flag)

    stop_name = 'f9'

    @Slot(ScriptEvent)
    def on_keyboard_event(event):
        key_name = event.action[1].lower()
        if key_name == stop_name:
            logger.debug('break exit!')
            flag.value = True
            thread.stop()
        return True

    Recorder.setuphook(commandline=True)
    Recorder.set_callback(on_keyboard_event)

    PluginManager.reload()
    eventloop = QApplication(sys.argv)

    thread.finished.connect(lambda: eventloop.exit(1 if thread.outcome == 'failed' else 0))
    thread.start()

    sys.exit(eventloop.exec_())


if __name__ == '__main__':
    logger.debug(sys.argv)
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser()
        parser.add_argument('scripts',
                            help='Path for the scripts',
                            type=str,
                            nargs='+'
                            )
        parser.add_argument('-rt', '--runtimes',
                            help='Run times for the script',
                            type=int,
                            default=1
                            )
        args = vars(parser.parse_args())
        logger.debug(args)
        try:
            single_run(args['scripts'], run_times=args['runtimes'])
        except Exception:
            logging.basicConfig(level=logging.ERROR)
            logging.exception('Command-line script failed')
            sys.exit(1)
    else:
        sys.exit(main())
