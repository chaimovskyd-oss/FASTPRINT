import os, sys
from dataclasses import dataclass
from pathlib import Path
from PySide6.QtCore import Qt, QRectF, QSize, QTimer, QSettings, QStandardPaths, QLockFile
from PySide6.QtGui import QImage, QPainter, QPixmap, QIcon, QPageLayout, QTransform, QImageReader
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintDialog
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QComboBox,
    QGraphicsView, QGraphicsScene, QMessageBox, QSplitter, QSpinBox, QFrame,
    QSizePolicy
)
try:
    from PySide6.QtGui import QPageSize
except Exception:
    QPageSize = None
try:
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
except Exception:
    QLocalServer = None
    QLocalSocket = None

try:
    from PIL import Image
except Exception:
    Image = None

SUPPORTED = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.gif'}
if Image is not None:
    SUPPORTED |= {'.heic', '.avif', '.jp2', '.jxl', '.psd', '.tga'}

APP_TITLE = 'הדפס תמונות חכם - חדיש v1.7'
ORG_NAME = 'Hadish'
APP_NAME = 'SmartPhotoPrint'
INSTANCE_LOCK = 'hadish_smart_photo_print_v16.lock'
INSTANCE_SERVER = 'hadish_smart_photo_print_v16_server'


def _pil_to_qimage(pil_image):
    if pil_image.mode != 'RGBA':
        pil_image = pil_image.convert('RGBA')
    data = pil_image.tobytes('raw', 'RGBA')
    qimg = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
    return qimg.copy()


def _load_image_file(path):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    # For animated formats take only the first frame
    if reader.supportsAnimation():
        reader.jumpToImage(0)
    img = reader.read()
    if not img.isNull():
        return img
    if Image is None:
        return QImage()
    try:
        with Image.open(path) as pil:
            # Composite frames (GIF/APNG/WEBP animated) onto white background
            if hasattr(pil, 'n_frames') and pil.n_frames > 1:
                pil.seek(0)
            pil = pil.convert('RGBA')
            bg = Image.new('RGBA', pil.size, (255, 255, 255, 255))
            bg.paste(pil, mask=pil.split()[3])
            return _pil_to_qimage(bg.convert('RGBA'))
    except Exception:
        return QImage()


@dataclass
class PhotoItem:
    path: str
    mode: str = 'Fill'
    pan_x: float = 0.0
    pan_y: float = 0.0
    copies: int = 1

class Preview(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.current = None
        self.paper_w = 420
        self.paper_h = 630
        self.dragging = False
        self.last_pos = None
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setAlignment(Qt.AlignCenter)
        self.setBackgroundBrush(Qt.lightGray)
        self.setMinimumSize(450, 420)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_photo(self, item, paper_ratio=2/3):
        self.current = item
        self.set_ratio(paper_ratio)
        self.update_view()

    def set_ratio(self, ratio):
        if not ratio or ratio <= 0:
            ratio = 2/3
        if ratio <= 1:
            self.paper_w = 430
            self.paper_h = max(260, int(self.paper_w / ratio))
        else:
            self.paper_h = 430
            self.paper_w = max(260, int(self.paper_h * ratio))

    def _auto_oriented_pixmap(self, pix):
        # Mimic Windows photo print: rotate the image for the best match to paper orientation.
        if pix.isNull():
            return pix
        paper_landscape = self.paper_w >= self.paper_h
        image_landscape = pix.width() >= pix.height()
        if paper_landscape != image_landscape:
            return pix.transformed(QTransform().rotate(90), Qt.SmoothTransformation)
        return pix

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.scene.sceneRect().isValid():
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def _source_rect(self, iw, ih, tw, th, item):
        if item.mode == 'Fit':
            return QRectF(0, 0, iw, ih)
        img_ratio = iw / ih
        target_ratio = tw / th
        if img_ratio > target_ratio:
            crop_h = ih
            crop_w = ih * target_ratio
            max_shift = max(0, (iw - crop_w) / 2)
            cx = iw / 2 + item.pan_x * max_shift
            x = max(0, min(iw - crop_w, cx - crop_w / 2))
            return QRectF(x, 0, crop_w, crop_h)
        crop_w = iw
        crop_h = iw / target_ratio
        max_shift = max(0, (ih - crop_h) / 2)
        cy = ih / 2 + item.pan_y * max_shift
        y = max(0, min(ih - crop_h, cy - crop_h / 2))
        return QRectF(0, y, crop_w, crop_h)

    def _load_pixmap(self, path):
        img = _load_image_file(path)
        if img.isNull():
            return QPixmap()
        return QPixmap.fromImage(img)

    def update_view(self):
        self.scene.clear()
        self.scene.setSceneRect(0, 0, self.paper_w, self.paper_h)
        # paper background + border
        self.scene.addRect(0, 0, self.paper_w, self.paper_h)
        if not self.current:
            txt = self.scene.addText('בחר תמונות להדפסה')
            txt.setPos(self.paper_w/2 - txt.boundingRect().width()/2, self.paper_h/2 - 20)
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            return
        if not os.path.exists(self.current.path):
            txt = self.scene.addText('קובץ לא נמצא')
            txt.setPos(20, 20)
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            return
        pix = self._load_pixmap(self.current.path)
        if pix.isNull():
            txt = self.scene.addText('לא ניתן לטעון את התמונה')
            txt.setPos(20, 20)
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            return
        pix = self._auto_oriented_pixmap(pix)
        target = QRectF(0, 0, self.paper_w, self.paper_h)
        if self.current.mode == 'Fit':
            scaled = pix.scaled(int(target.width()), int(target.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item = self.scene.addPixmap(scaled)
            item.setPos((self.paper_w - scaled.width())/2, (self.paper_h - scaled.height())/2)
        else:
            src = self._source_rect(pix.width(), pix.height(), target.width(), target.height(), self.current)
            cropped = pix.copy(src.toRect())
            scaled = cropped.scaled(int(target.width()), int(target.height()), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            item = self.scene.addPixmap(scaled)
            item.setPos(0, 0)
        self.scene.addRect(0, 0, self.paper_w, self.paper_h)
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        if self.current and self.current.mode == 'Fill' and event.button() == Qt.LeftButton:
            self.dragging = True
            self.last_pos = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragging and self.current:
            delta = event.position() - self.last_pos
            self.last_pos = event.position()
            self.current.pan_x = max(-1, min(1, self.current.pan_x - delta.x()/140))
            self.current.pan_y = max(-1, min(1, self.current.pan_y - delta.y()/140))
            self.update_view()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.dragging = False
        super().mouseReleaseEvent(event)

class MainWindow(QMainWindow):
    def __init__(self, paths):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        icon_path = Path(__file__).resolve().parent.parent / 'assets' / 'hadish_printer.ico'
        if icon_path.exists(): self.setWindowIcon(QIcon(str(icon_path)))
        self.items = [PhotoItem(str(Path(p))) for p in paths if Path(p).suffix.lower() in SUPPORTED and Path(p).exists()]
        self.current_index = -1
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.printer = QPrinter(QPrinter.HighResolution)
        self.printer.setFullPage(True)  # WYSIWYG: preview and print use the full selected paper canvas
        self.printers = []
        self._building = False
        self._build_ui()
        QApplication.instance().installEventFilter(self)
        self.load_printers()
        saved_orientation = self.settings.value('printer/orientation', '', str)
        if saved_orientation in ('Portrait', 'Landscape'):
            self.orientation_combo.setCurrentText(saved_orientation)
        if self.items:
            self.refresh_list(); self.list.setCurrentRow(0)
        else:
            self.preview.set_photo(None, self.current_paper_ratio())

    def _build_ui(self):
        self.setStyleSheet('''
            QWidget { font-size: 9pt; color:#202020; }
            QMainWindow { background:#f5f7fa; }
            QFrame#TopBar { background:#eef4fb; border-bottom:1px solid #c7d2df; }
            QPushButton { background:#ffffff; color:#202020; border:1px solid #aeb8c4; border-radius:5px; padding:4px 9px; min-height:22px; }
            QPushButton:hover { background:#f3f7fb; }
            QPushButton:pressed { background:#dfeaf5; }
            QComboBox, QSpinBox { background:#ffffff; color:#111111; border:1px solid #aeb8c4; border-radius:5px; padding:2px 6px; min-height:22px; selection-background-color:#cfe3ff; selection-color:#111111; }
            QComboBox QAbstractItemView { background:#ffffff; color:#111111; selection-background-color:#cfe3ff; selection-color:#111111; }
            QListWidget { background:#ffffff; color:#111111; border:1px solid #c7d2df; }
            QListWidget::item:selected { background:#dcecff; color:#111111; }
            QLabel { color:#263238; }
        ''')
        root = QWidget(); outer = QVBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        top = QFrame(); top.setObjectName('TopBar'); tl = QHBoxLayout(top); tl.setContentsMargins(6,3,6,3); tl.setSpacing(5)
        self.add_btn = QPushButton('הוסף תמונות'); self.add_btn.clicked.connect(self.add_files); tl.addWidget(self.add_btn)
        self.print_btn = QPushButton('הדפס'); self.print_btn.clicked.connect(self.print_now); tl.addWidget(self.print_btn)
        tl.addStretch(1)
        tl.addWidget(QLabel('מדפסת'))
        self.printer_combo = QComboBox(); self.printer_combo.setMinimumWidth(220); self.printer_combo.currentIndexChanged.connect(self.printer_changed); tl.addWidget(self.printer_combo)
        tl.addWidget(QLabel('נייר'))
        self.paper_combo = QComboBox(); self.paper_combo.setMinimumWidth(240); self.paper_combo.currentIndexChanged.connect(self.paper_changed); tl.addWidget(self.paper_combo)
        tl.addWidget(QLabel('כיוון'))
        self.orientation_combo = QComboBox(); self.orientation_combo.addItems(['Portrait','Landscape']); self.orientation_combo.currentTextChanged.connect(self.orientation_changed); tl.addWidget(self.orientation_combo)
        self.driver_btn = QPushButton('הגדרות'); self.driver_btn.clicked.connect(self.open_driver_dialog); tl.addWidget(self.driver_btn)
        outer.addWidget(top)

        splitter = QSplitter(); outer.addWidget(splitter, 1)
        left = QWidget(); left_l = QVBoxLayout(left); left_l.setContentsMargins(8,8,8,8)
        left_l.addWidget(QLabel('תמונות'))
        self.list = QListWidget(); self.list.setUniformItemSizes(True); self.list.currentRowChanged.connect(self.select_index); left_l.addWidget(self.list, 1)
        self.mode = QComboBox(); self.mode.addItems(['Fill','Fit']); self.mode.currentTextChanged.connect(self.mode_changed); left_l.addWidget(QLabel('Fit / Fill לתמונה')) ; left_l.addWidget(self.mode)
        self.copies = QSpinBox(); self.copies.setRange(1,99); self.copies.valueChanged.connect(self.copies_changed); left_l.addWidget(QLabel('עותקים')); left_l.addWidget(self.copies)
        row = QHBoxLayout(); b1=QPushButton('Fill לכולם'); b1.clicked.connect(lambda:self.apply_mode_all('Fill')); b2=QPushButton('Fit לכולם'); b2.clicked.connect(lambda:self.apply_mode_all('Fit')); row.addWidget(b1); row.addWidget(b2); left_l.addLayout(row)
        breset=QPushButton('אפס מיקום'); breset.clicked.connect(self.reset_pan); left_l.addWidget(breset)
        splitter.addWidget(left)
        center = QWidget(); center_l=QVBoxLayout(center); center_l.setContentsMargins(8,8,8,8)
        self.preview = Preview(); center_l.addWidget(self.preview,1)
        self.status = QLabel('רווח: Fit/Fill  |  חיצים: מעבר תמונות  |  WASD / שודג בעברית / גרירה: הזזה ב-Fill')
        self.status.setAlignment(Qt.AlignCenter); center_l.addWidget(self.status)
        splitter.addWidget(center)
        splitter.setSizes([260, 900])
        self.setCentralWidget(root); self.resize(1180,760); self.setFocusPolicy(Qt.StrongFocus)

    def load_printers(self):
        self._building = True
        self.printer_combo.clear(); self.printers = QPrinterInfo.availablePrinters()
        default_name = QPrinterInfo.defaultPrinterName()
        saved_name = self.settings.value('printer/name', '', str)
        chosen_idx = 0
        for i, info in enumerate(self.printers):
            name = info.printerName(); self.printer_combo.addItem(name)
            if name == default_name and not saved_name:
                chosen_idx = i
            if saved_name and name == saved_name:
                chosen_idx = i
        self._building = False
        if self.printers:
            self.printer_combo.setCurrentIndex(chosen_idx); self.printer_changed(chosen_idx)

    def printer_changed(self, idx):
        if self._building or idx < 0 or idx >= len(self.printers): return
        info = self.printers[idx]
        self.printer = QPrinter(info, QPrinter.HighResolution)
        self.apply_printer_layout()
        self.settings.setValue('printer/name', info.printerName())
        self.load_papers(info)
        self.update_preview()

    def load_papers(self, info):
        self._building = True
        self.paper_combo.clear()
        sizes = []
        try: sizes = info.supportedPageSizes()
        except Exception: sizes = []
        seen=set()
        for ps in sizes:
            try:
                name = ps.name() or ps.key() or 'Paper'
                r = ps.rect(QPageSize.Millimeter)
                w = float(r.width()); h = float(r.height())
                if w <= 0 or h <= 0:
                    continue
                label = f'{name}  ({w:.0f}×{h:.0f} mm)'
                key=(name, int(round(w)), int(round(h)))
                if key in seen: continue
                seen.add(key)
                # Store the dimensions ourselves too. Some Windows drivers/Qt builds
                # accept the selected QPageSize for printing but do not immediately
                # reflect it back through printer.pageLayout(), which made the preview
                # stay stuck on A4. The preview must follow this stored data.
                self.paper_combo.addItem(label, (ps, w, h))
            except Exception:
                pass
        if self.paper_combo.count()==0:
            self.paper_combo.addItem('לפי ברירת המחדל של הדרייבר', None)
        saved_label = self.settings.value('printer/paper_label', '', str)
        saved_size = self.settings.value('printer/paper_size_mm', '', str)
        chosen = 0
        for i in range(self.paper_combo.count()):
            label = self.paper_combo.itemText(i)
            data = self.paper_combo.itemData(i)
            size_key = ''
            if isinstance(data, tuple) and len(data) >= 3:
                size_key = f'{round(float(data[1]), 1)}x{round(float(data[2]), 1)}'
            if saved_label and label == saved_label:
                chosen = i; break
            if saved_size and size_key == saved_size:
                chosen = i
        self._building = False
        if self.paper_combo.count():
            self.paper_combo.setCurrentIndex(chosen)
        self.paper_changed(self.paper_combo.currentIndex())

    def paper_changed(self, idx):
        if self._building: return
        data = self.paper_combo.currentData()
        self.settings.setValue('printer/paper_label', self.paper_combo.currentText())
        if isinstance(data, tuple) and len(data) >= 3:
            self.settings.setValue('printer/paper_size_mm', f'{round(float(data[1]), 1)}x{round(float(data[2]), 1)}')
        self.apply_printer_layout()
        self.update_preview()

    def orientation_changed(self, text):
        if self._building: return
        self.settings.setValue('printer/orientation', text)
        self.apply_printer_layout()
        self.update_preview()

    def open_driver_dialog(self):
        dlg = QPrintDialog(self.printer, self); dlg.setWindowTitle('מאפייני מדפסת / דרייבר')
        if dlg.exec() == QPrintDialog.Accepted:
            self.update_preview()

    def current_paper_ratio(self):
        # The preview ratio must be controlled by the paper dropdown immediately,
        # not by a delayed/driver-dependent QPrinter pageLayout refresh.
        try:
            data = self.paper_combo.currentData()
            if data is not None:
                if isinstance(data, tuple) and len(data) >= 3:
                    w, h = float(data[1]), float(data[2])
                else:
                    r = data.rect(QPageSize.Millimeter)
                    w, h = float(r.width()), float(r.height())
                if self.orientation_combo.currentText() == 'Landscape':
                    w, h = max(w, h), min(w, h)
                else:
                    w, h = min(w, h), max(w, h)
                if w > 0 and h > 0:
                    return w / h
        except Exception:
            pass
        try:
            r = self.printer.pageLayout().fullRect(QPageLayout.Millimeter)
            if r.width()>0 and r.height()>0: return float(r.width())/float(r.height())
        except Exception: pass
        return 2/3

    def refresh_list(self, preserve_row=None):
        if preserve_row is None: preserve_row = self.list.currentRow() if hasattr(self,'list') else -1
        self.list.blockSignals(True); self.list.clear()
        for it in self.items:
            self.list.addItem(QListWidgetItem(f'{Path(it.path).name}  [{it.mode}] x{it.copies}'))
        self.list.blockSignals(False)
        if self.items: self.list.setCurrentRow(max(0,min(preserve_row,len(self.items)-1)))
        else: self.preview.set_photo(None, self.current_paper_ratio())

    def select_index(self, idx):
        self.current_index = idx
        if 0 <= idx < len(self.items):
            it=self.items[idx]
            self.mode.blockSignals(True); self.mode.setCurrentText(it.mode); self.mode.blockSignals(False)
            self.copies.blockSignals(True); self.copies.setValue(it.copies); self.copies.blockSignals(False)
            self.preview.set_photo(it, self.current_paper_ratio())

    def add_external_paths(self, paths):
        existing={str(Path(i.path).resolve()) for i in self.items}
        added = 0
        for raw in paths:
            try:
                p = Path(str(raw).strip().strip('"')).resolve()
            except Exception:
                continue
            if p.exists() and p.suffix.lower() in SUPPORTED and str(p) not in existing:
                self.items.append(PhotoItem(str(p)))
                existing.add(str(p)); added += 1
        if added:
            was_empty = self.current_index < 0
            self.refresh_list(self.list.currentRow())
            if was_empty and self.items:
                self.list.setCurrentRow(0)

    def add_files(self):
        extensions = ' '.join(f'*.{ext.lstrip(".")}' for ext in sorted(SUPPORTED))
        files,_=QFileDialog.getOpenFileNames(self,'בחר תמונות','',f'Images ({extensions})')
        self.add_external_paths(files)

    def mode_changed(self, text):
        if 0 <= self.current_index < len(self.items):
            self.items[self.current_index].mode=text; self.update_current_list_row(); self.update_preview()
    def copies_changed(self, val):
        if 0 <= self.current_index < len(self.items): self.items[self.current_index].copies=val; self.update_current_list_row()
    def apply_mode_all(self, mode):
        for it in self.items: it.mode=mode
        self.refresh_list(self.list.currentRow()); self.select_index(self.list.currentRow())
    def reset_pan(self):
        if 0 <= self.current_index < len(self.items):
            self.items[self.current_index].pan_x=0; self.items[self.current_index].pan_y=0; self.update_preview()
    def update_current_list_row(self):
        row=self.current_index
        if 0 <= row < len(self.items):
            it=self.items[row]; self.list.item(row).setText(f'{Path(it.path).name}  [{it.mode}] x{it.copies}')
    def update_preview(self):
        self.preview.set_photo(self.items[self.current_index] if 0 <= self.current_index < len(self.items) else None, self.current_paper_ratio())


    def normalize_nudge_key(self, event):
        # Support both English and Hebrew keyboard layouts.
        # Physical WASD on a Hebrew keyboard usually produces: W=ו, A=ש, S=ד, D=ג.
        txt = (event.text() or '').lower()
        hebrew_map = {'ו': 'w', 'ש': 'a', 'ד': 's', 'ג': 'd'}
        if txt in ('w', 'a', 's', 'd'):
            return txt
        if txt in hebrew_map:
            return hebrew_map[txt]
        # On Windows, nativeVirtualKey stays the physical Latin key even when the layout is Hebrew.
        try:
            vk = event.nativeVirtualKey()
            vk_map = {0x57: 'w', 0x41: 'a', 0x53: 's', 0x44: 'd'}
            if vk in vk_map:
                return vk_map[vk]
        except Exception:
            pass
        return ''

    def eventFilter(self, obj, event):
        # Keep shortcuts working even when the list, preview, comboboxes, or buttons have focus.
        if event.type() == event.Type.KeyPress:
            key = event.key()
            nudge_key = self.normalize_nudge_key(event)
            if key in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Left, Qt.Key_Up, Qt.Key_Space) or nudge_key:
                self.handle_shortcut_key(key, nudge_key)
                return True
        return super().eventFilter(obj, event)

    def handle_shortcut_key(self, key, nudge_key=''):
        if not self.items:
            return
        if key in (Qt.Key_Right, Qt.Key_Down):
            self.list.setCurrentRow(min(len(self.items)-1, self.list.currentRow()+1)); return
        if key in (Qt.Key_Left, Qt.Key_Up):
            self.list.setCurrentRow(max(0, self.list.currentRow()-1)); return
        if key == Qt.Key_Space:
            self.toggle_current(); return
        if nudge_key in ('w','a','s','d'):
            self.nudge(nudge_key); return

    def keyPressEvent(self, event):
        self.handle_shortcut_key(event.key(), self.normalize_nudge_key(event))
    def toggle_current(self):
        if 0 <= self.current_index < len(self.items):
            it=self.items[self.current_index]; it.mode='Fit' if it.mode=='Fill' else 'Fill'
            self.mode.blockSignals(True); self.mode.setCurrentText(it.mode); self.mode.blockSignals(False)
            self.update_current_list_row(); self.update_preview()
    def nudge(self,key):
        if 0 <= self.current_index < len(self.items):
            it=self.items[self.current_index]
            if it.mode!='Fill': return
            step=0.045
            if key=='a': it.pan_x=max(-1,it.pan_x-step)
            elif key=='d': it.pan_x=min(1,it.pan_x+step)
            elif key=='w': it.pan_y=max(-1,it.pan_y-step)
            elif key=='s': it.pan_y=min(1,it.pan_y+step)
            self.update_preview()

    def _load_image_for_print(self, path):
        # Load through the same image loader used by preview so print and preview agree.
        return _load_image_file(path)

    def get_selected_paper_dimensions(self):
        data = self.paper_combo.currentData()
        if isinstance(data, tuple) and len(data) >= 3:
            return float(data[1]), float(data[2])
        try:
            r = self.printer.paperRect(QPrinter.Millimeter)
            if r.width() > 0 and r.height() > 0:
                return float(r.width()), float(r.height())
        except Exception:
            pass
        try:
            r = self.printer.pageLayout().fullRect(QPageLayout.Millimeter)
            if r.width() > 0 and r.height() > 0:
                return float(r.width()), float(r.height())
        except Exception:
            pass
        return 0.0, 0.0

    def apply_printer_layout(self):
        try:
            self.printer.setFullPage(True)
        except Exception:
            pass
        try:
            self.printer.setPageMargins(0, 0, 0, 0, QPrinter.Millimeter)
        except Exception:
            pass
        orientation = self.orientation_combo.currentText()
        try:
            self.printer.setOrientation(QPrinter.Landscape if orientation == 'Landscape' else QPrinter.Portrait)
        except Exception:
            pass
        try:
            layout = self.printer.pageLayout()
            layout.setOrientation(QPageLayout.Landscape if orientation == 'Landscape' else QPageLayout.Portrait)
            data = self.paper_combo.currentData()
            if isinstance(data, tuple) and data[0] is not None:
                layout.setPageSize(data[0])
            self.printer.setPageLayout(layout)
        except Exception:
            pass

    def print_now(self):
        if not self.items:
            QMessageBox.warning(self,'אין תמונות','לא נבחרו תמונות להדפסה'); return
        self.apply_printer_layout()
        total = sum(it.copies for it in self.items)
        painter = QPainter(self.printer)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        first = True
        page_num = 0
        failed = []
        for it in self.items:
            for _ in range(it.copies):
                if not first:
                    self.printer.newPage()
                first = False
                page_num += 1
                if total > 1:
                    self.status.setText(f'מדפיס {page_num} מתוך {total}...')
                    QApplication.processEvents()
                try:
                    self.paint_photo(painter, self.printer, it)
                except Exception:
                    failed.append(Path(it.path).name)
        painter.end()
        self.status.setText('רווח: Fit/Fill  |  חיצים: מעבר תמונות  |  WASD / שודג בעברית / גרירה: הזזה ב-Fill')
        msg = f'{total} דפים נשלחו למדפסת'
        if failed:
            msg += f'\n\nכשלו: {", ".join(failed)}'
        QMessageBox.information(self, 'נשלח להדפסה', msg)

    def _auto_oriented_image(self, img, tw, th):
        paper_landscape = tw >= th
        image_landscape = img.width() >= img.height()
        if paper_landscape != image_landscape:
            return img.transformed(QTransform().rotate(90), Qt.SmoothTransformation)
        return img

    def _fill_source_rect(self, iw, ih, tw, th, it):
        # Single crop calculation used by the real print path.
        # pan_x/pan_y are normalized -1..1 exactly like the preview.
        ir = iw / ih
        tr = tw / th
        if ir > tr:
            crop_h = ih
            crop_w = ih * tr
            max_shift = max(0, (iw - crop_w) / 2)
            cx = iw / 2 + it.pan_x * max_shift
            x = max(0, min(iw - crop_w, cx - crop_w / 2))
            return QRectF(x, 0, crop_w, crop_h)
        else:
            crop_w = iw
            crop_h = iw / tr
            max_shift = max(0, (ih - crop_h) / 2)
            cy = ih / 2 + it.pan_y * max_shift
            y = max(0, min(ih - crop_h, cy - crop_h / 2))
            return QRectF(0, y, crop_w, crop_h)

    def paint_photo(self, painter, printer, it):
        img = self._load_image_for_print(it.path)
        if img.isNull():
            return

        # dest rect on the printer canvas (device pixels, full paper including bleed)
        try:
            rect = QRectF(printer.paperRect(QPrinter.DevicePixel))
        except Exception:
            rect = QRectF(printer.pageRect(QPrinter.DevicePixel))
        if rect.width() <= 0 or rect.height() <= 0:
            return

        # Derive the canvas dimensions from the paper combo (mm) + printer DPI so that
        # the crop/pan calculation uses the exact same aspect ratio as the preview.
        # Relying on paperRect() aspect ratio alone can fail for photo dye-sub drivers
        # (e.g. Mitsubishi D80) that report a slightly different bleed canvas, and for
        # deprecated setOrientation() calls that may not update paperRect() in Qt6.
        w_mm, h_mm = self.get_selected_paper_dimensions()
        orientation = self.orientation_combo.currentText()
        if orientation == 'Landscape':
            w_mm, h_mm = max(w_mm, h_mm), min(w_mm, h_mm)
        else:
            w_mm, h_mm = min(w_mm, h_mm), max(w_mm, h_mm)

        if w_mm > 0 and h_mm > 0:
            dpi = printer.resolution()
            if dpi <= 0:
                dpi = 300
            tw = max(1, int(round(w_mm / 25.4 * dpi)))
            th = max(1, int(round(h_mm / 25.4 * dpi)))
        else:
            tw = int(round(rect.width()))
            th = int(round(rect.height()))

        # Safety cap: photo printers are normally 300-600 DPI.
        max_dim = 9000
        scale = min(1.0, max_dim / max(tw, th))
        page_w = max(1, int(round(tw * scale)))
        page_h = max(1, int(round(th * scale)))

        img = self._auto_oriented_image(img, page_w, page_h)
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return

        page = QImage(page_w, page_h, QImage.Format_RGB32)
        page.fill(Qt.white)
        pp = QPainter(page)
        pp.setRenderHint(QPainter.SmoothPixmapTransform, True)

        target_full = QRectF(0, 0, page_w, page_h)
        if it.mode == 'Fit':
            ir = iw / ih
            tr = page_w / page_h
            if ir > tr:
                dw = page_w
                dh = page_w / ir
            else:
                dh = page_h
                dw = page_h * ir
            target = QRectF((page_w - dw) / 2, (page_h - dh) / 2, dw, dh)
            pp.drawImage(target, img, QRectF(0, 0, iw, ih))
        else:
            src = self._fill_source_rect(iw, ih, page_w, page_h, it)
            pp.drawImage(target_full, img, src)
        pp.end()

        painter.drawImage(rect, page, QRectF(0, 0, page_w, page_h))

def _clean_args(args):
    paths=[]
    for arg in args:
        p=str(arg).strip().strip('"')
        try:
            pp=Path(p)
            if pp.exists() and pp.suffix.lower() in SUPPORTED:
                paths.append(str(pp.resolve()))
        except Exception:
            pass
    return paths


def _send_to_existing_instance(paths, timeout_ms=900):
    if not paths or QLocalSocket is None:
        return False
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_SERVER)
    if not sock.waitForConnected(timeout_ms):
        return False
    payload = '\n'.join(paths).encode('utf-8')
    sock.write(payload)
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


def _lock_path():
    base = QStandardPaths.writableLocation(QStandardPaths.TempLocation) or os.environ.get('TEMP') or os.getcwd()
    return str(Path(base) / INSTANCE_LOCK)


def main():
    app=QApplication(sys.argv)
    paths=_clean_args(sys.argv[1:])

    # Single-instance protection: Explorer may launch one process per selected file.
    # Later launches send their files into the already-open window instead of opening
    # a separate window. QLockFile prevents race conditions during the first launch.
    lock = QLockFile(_lock_path())
    lock.setStaleLockTime(0)
    if not lock.tryLock(150):
        # Another process is probably starting or already running. Give it a moment,
        # then pass these files to it and exit.
        if _send_to_existing_instance(paths, 2500):
            return
        # Fallback: wait a bit more for the first window to finish creating the server.
        QTimer.singleShot(600, app.quit)
        app.exec()
        if _send_to_existing_instance(paths, 2500):
            return
        # If something went wrong with a stale lock, continue and open a window.

    w=MainWindow(paths)
    server = None
    if QLocalServer is not None:
        try:
            QLocalServer.removeServer(INSTANCE_SERVER)
        except Exception:
            pass
        server = QLocalServer(w)
        def receive_files():
            while server.hasPendingConnections():
                sock = server.nextPendingConnection()
                if sock.waitForReadyRead(1200):
                    data = bytes(sock.readAll()).decode('utf-8', errors='ignore')
                    w.add_external_paths(data.splitlines())
                    w.raise_(); w.activateWindow()
                sock.disconnectFromServer()
        server.newConnection.connect(receive_files)
        server.listen(INSTANCE_SERVER)
    w.show()
    code=app.exec()
    try:
        lock.unlock()
    except Exception:
        pass
    sys.exit(code)
if __name__=='__main__': main()
