# --- CORRECTION CRITIQUE TERMUX:WIDGET ---
# Doit être en TOUT PREMIER avant tout autre import
import os
import sys
import tempfile

if os.path.exists("/data/data/com.termux"):
    termux_tmp = "/data/data/com.termux/files/home/.tmp"
    os.makedirs(termux_tmp, exist_ok=True)
    os.environ["TMPDIR"] = termux_tmp
    tempfile.tempdir     = termux_tmp
    # Sous Termux:Widget, stdout/stderr n'existent pas — les print() plantent
    try:
        if not sys.stdout or not sys.stdout.isatty():
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = open(os.devnull, 'w')
    except Exception:
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
# ------------------------------------------

# --- Imports critiques avec messages d'erreur explicites ---
try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ImportError:
    raise SystemExit(
        "Erreur : la bibliothèque 'fpdf2' est introuvable.\n"
        "Installez-la avec : pip install fpdf2\n"
        "(Attention : 'fpdf' et 'fpdf2' sont deux paquets différents — utilisez bien 'fpdf2')"
    )

HEIF_DISPONIBLE = False
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_DISPONIBLE = True
except ImportError:
    print(
        "Info : pillow_heif non installé — les fichiers .HEIC ne seront pas supportés.\n"
        "Pour l'activer : pip install pillow-heif"
    )

# os déjà importé en tête — pas de double import
import io
import re
import time
import socket
import platform
import subprocess
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, send_file, jsonify, Response
from PIL import Image
import logging

app = Flask(__name__)

# Désactiver tout logging Flask/Werkzeug pour compatibilité Termux:Widget
logging.getLogger('werkzeug').disabled = True
logging.getLogger('werkzeug').setLevel(logging.ERROR)
app.logger.disabled   = True
app.logger.propagate  = False

VERSION = "1.9"

# --- HTML de l'interface ---
HTML = r"""
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Générateur PDF Album</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: Arial, sans-serif;
            background: #f0f2f5;
            padding: 20px;
            color: #222;
        }
        h1 {
            text-align: center;
            margin-bottom: 4px;
            color: #0056b3;
            font-size: 1.4em;
        }
        .version {
            text-align: center;
            font-size: 0.78em;
            color: #aaa;
            margin-bottom: 20px;
        }
        .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        label {
            display: block;
            font-weight: bold;
            margin-bottom: 6px;
            font-size: 0.95em;
        }
        input[type="text"], input[type="number"], textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 8px;
            font-size: 1em;
        }
        textarea { height: 100px; resize: vertical; }
        input[type="file"] { display: none; }

        .option-ligne {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-top: 4px;
        }
        .option-ligne input[type="number"] {
            width: 90px;
            flex-shrink: 0;
        }
        .option-ligne input[type="checkbox"] {
            width: 18px;
            height: 18px;
            flex-shrink: 0;
            cursor: pointer;
        }
        .option-ligne label {
            margin: 0;
            font-weight: normal;
            cursor: pointer;
        }

        .btn-photos {
            display: block;
            width: 100%;
            padding: 14px;
            background: #e8f0fe;
            color: #0056b3;
            border: 2px dashed #0056b3;
            border-radius: 8px;
            font-size: 1em;
            font-weight: bold;
            text-align: center;
            cursor: pointer;
        }
        #photo-count {
            text-align: center;
            margin-top: 8px;
            font-size: 0.9em;
            color: #888;
        }
        #photo-count.ok { color: #28a745; font-weight: bold; }

        #preview {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
            touch-action: none;
        }
        .thumb-wrap {
            position: relative;
            width: 120px;
            height: 120px;
            background: #e0e0e0;
            border-radius: 8px;
            border: 2px solid #ddd;
            cursor: grab;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            user-select: none;
            -webkit-user-select: none;
        }
        .thumb-wrap.dragging  { opacity: 0.4; border-color: #0056b3; }
        .thumb-wrap.drag-over { border-color: #0056b3; border-style: dashed; }
        .thumb-wrap img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            border-radius: 6px;
            pointer-events: none;
        }
        .thumb-num {
            position: absolute;
            top: 4px; left: 4px;
            background: rgba(0,0,0,0.55);
            color: white;
            font-size: 0.72em;
            padding: 1px 5px;
            border-radius: 4px;
            pointer-events: none;
        }
        .thumb-warn {
            position: absolute;
            bottom: 4px; left: 0; right: 0;
            text-align: center;
            background: rgba(220,53,69,0.85);
            color: white;
            font-size: 0.68em;
            padding: 2px 4px;
            pointer-events: none;
        }
        .thumb-spinner {
            width: 28px; height: 28px;
            border: 3px solid #ccc;
            border-top-color: #0056b3;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        #touch-ghost {
            position: fixed;
            pointer-events: none;
            opacity: 0.75;
            border-radius: 8px;
            border: 2px solid #0056b3;
            overflow: hidden;
            display: none;
            z-index: 9999;
            width: 120px; height: 120px;
        }

        .btn-generate {
            display: block;
            width: 100%;
            padding: 16px;
            background: #0056b3;
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1.1em;
            font-weight: bold;
            cursor: pointer;
            margin-top: 8px;
        }
        .btn-generate:disabled { background: #aaa; cursor: not-allowed; }

        #progress-wrap { display: none; margin-top: 14px; }
        #progress-bar-bg {
            width: 100%; height: 14px;
            background: #ddd; border-radius: 8px; overflow: hidden;
        }
        #progress-bar {
            height: 100%; width: 0%;
            background: #0056b3; border-radius: 8px;
            transition: width 0.3s;
        }
        #progress-label {
            text-align: center; font-size: 0.88em;
            color: #555; margin-top: 5px;
        }
        #status {
            text-align: center; margin-top: 12px;
            font-size: 0.95em; min-height: 24px;
        }
        #status.error   { color: #dc3545; }
        #status.success { color: #28a745; }
        #status.loading { color: #0056b3; }
    </style>
</head>
<body>
    <h1>Générateur PDF Album</h1>
    <div class="version">v__VERSION__</div>

    <div id="touch-ghost"></div>

    <form id="form">
        <div class="card">
            <label for="titre">Titre</label>
            <input type="text" id="titre" name="titre" placeholder="Ex : Voyage en Bretagne" required>
        </div>

        <div class="card">
            <label for="description">Description</label>
            <textarea id="description" name="description" placeholder="Quelques mots sur cet album..."></textarea>
        </div>

        <div class="card">
            <label>Taille de l'espace notes sous les photos (mm)</label>
            <div class="option-ligne">
                <input type="number" id="esp_notes" name="esp_notes" value="16" min="0" step="1">
            </div>
        </div>

        <div class="card">
            <div class="option-ligne">
                <input type="checkbox" id="numerotation" name="numerotation">
                <label for="numerotation">Afficher le numéro de page en bas de chaque page</label>
            </div>
        </div>

        <div class="card">
            <div class="option-ligne">
                <input type="checkbox" id="max3parligne" name="max3parligne" checked>
                <label for="max3parligne">3 photos maximum par ligne</label>
            </div>
        </div>

        <div class="card">
            <div class="option-ligne">
                <input type="checkbox" id="ajustertaille" name="ajustertaille" checked>
                <label for="ajustertaille">Taille des photos ajustée au nombre de pages. Taille par défaut : 4,3 cm.</label>
            </div>
        </div>

        <div class="card">
            <label>Photos</label>
            <label for="photos" class="btn-photos">Choisir des photos</label>
            <input type="file" id="photos" name="photos" multiple accept="image/*,.heic,.HEIC">
            <div id="photo-count">Aucune photo sélectionnée</div>
            <div id="preview"></div>
        </div>

        <button type="submit" class="btn-generate" id="btn" disabled>
            GÉNÉRER LE PDF
        </button>

        <div id="progress-wrap">
            <div id="progress-bar-bg"><div id="progress-bar"></div></div>
            <div id="progress-label">Démarrage...</div>
        </div>

        <div id="status"></div>
    </form>

    <script>
        const input     = document.getElementById('photos');
        const countEl   = document.getElementById('photo-count');
        const preview   = document.getElementById('preview');
        const btn       = document.getElementById('btn');
        const status    = document.getElementById('status');
        const progWrap  = document.getElementById('progress-wrap');
        const progBar   = document.getElementById('progress-bar');
        const progLabel = document.getElementById('progress-label');
        const ghost     = document.getElementById('touch-ghost');

        const LIMIT_MB      = 20;
        const MAX_PX_UPLOAD = 1200;
        const JPEG_QUALITY  = 0.72;
        let orderedFiles    = [];
        let compressedBlobs = [];

        function compresserCanvas(file) {
            return new Promise(resolve => {
                const ext = file.name.split('.').pop().toLowerCase();
                if (ext === 'heic') { resolve(file); return; }
                const img = new window.Image();
                const url = URL.createObjectURL(file);
                img.onload = () => {
                    URL.revokeObjectURL(url);
                    let w = img.naturalWidth, h = img.naturalHeight;
                    if (Math.max(w, h) > MAX_PX_UPLOAD) {
                        if (w >= h) { h = Math.round(h * MAX_PX_UPLOAD / w); w = MAX_PX_UPLOAD; }
                        else        { w = Math.round(w * MAX_PX_UPLOAD / h); h = MAX_PX_UPLOAD; }
                    }
                    const canvas = document.createElement('canvas');
                    canvas.width = w; canvas.height = h;
                    canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                    canvas.toBlob(blob => resolve(blob || file), 'image/jpeg', JPEG_QUALITY);
                };
                img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
                img.src = url;
            });
        }

        async function preCompresserTout(files) {
            progWrap.style.display = 'block';
            progBar.style.width = '0%';
            progLabel.textContent = 'Pré-compression des images...';
            const results = [];
            for (let i = 0; i < files.length; i++) {
                results.push(await compresserCanvas(files[i]));
                const pct = Math.round((i + 1) / files.length * 100);
                progBar.style.width = pct + '%';
                progLabel.textContent = 'Pré-compression : ' + (i + 1) + '/' + files.length;
            }
            progWrap.style.display = 'none';
            progBar.style.width = '0%';
            return results;
        }

        let dragSrcIndex = null;

        function ajouterDragSouris(wrap) {
            wrap.draggable = true;
            wrap.addEventListener('dragstart', e => {
                dragSrcIndex = parseInt(wrap.dataset.index);
                wrap.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            });
            wrap.addEventListener('dragend', () => {
                wrap.classList.remove('dragging');
                document.querySelectorAll('.thumb-wrap').forEach(w => w.classList.remove('drag-over'));
            });
            wrap.addEventListener('dragover', e => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                wrap.classList.add('drag-over');
            });
            wrap.addEventListener('dragleave', () => wrap.classList.remove('drag-over'));
            wrap.addEventListener('drop', e => {
                e.preventDefault();
                const destIndex = parseInt(wrap.dataset.index);
                if (dragSrcIndex !== null && dragSrcIndex !== destIndex)
                    deplacerVignette(dragSrcIndex, destIndex);
                dragSrcIndex = null;
            });
        }

        let touchSrcIndex   = null;
        let touchSrcWrap    = null;
        let touchLastTarget = null;
        let touchHoldTimer  = null;
        const HOLD_DELAY    = 300;

        function ajouterDragTactile(wrap) {
            wrap.addEventListener('touchstart', e => {
                touchHoldTimer = setTimeout(() => {
                    touchSrcIndex = parseInt(wrap.dataset.index);
                    touchSrcWrap  = wrap;
                    wrap.classList.add('dragging');
                    ghost.innerHTML = wrap.innerHTML;
                    ghost.style.display = 'block';
                    positionnerGhost(e.touches[0]);
                }, HOLD_DELAY);
            }, { passive: true });

            wrap.addEventListener('touchmove', e => {
                if (touchSrcIndex === null) { clearTimeout(touchHoldTimer); return; }
                e.preventDefault();
                const touch = e.touches[0];
                positionnerGhost(touch);
                ghost.style.display = 'none';
                const el = document.elementFromPoint(touch.clientX, touch.clientY);
                ghost.style.display = 'block';
                const cible = el ? el.closest('.thumb-wrap') : null;
                if (touchLastTarget && touchLastTarget !== touchSrcWrap)
                    touchLastTarget.classList.remove('drag-over');
                if (cible && cible !== touchSrcWrap) {
                    cible.classList.add('drag-over');
                    touchLastTarget = cible;
                }
            }, { passive: false });

            wrap.addEventListener('touchend', e => {
                clearTimeout(touchHoldTimer);
                if (touchSrcIndex === null) return;
                ghost.style.display = 'none';
                touchSrcWrap.classList.remove('dragging');
                if (touchLastTarget) touchLastTarget.classList.remove('drag-over');
                const touch = e.changedTouches[0];
                const el = document.elementFromPoint(touch.clientX, touch.clientY);
                const cible = el ? el.closest('.thumb-wrap') : null;
                if (cible && cible !== touchSrcWrap)
                    deplacerVignette(touchSrcIndex, parseInt(cible.dataset.index));
                touchSrcIndex = null; touchSrcWrap = null; touchLastTarget = null;
            });

            wrap.addEventListener('touchcancel', () => {
                clearTimeout(touchHoldTimer);
                ghost.style.display = 'none';
                if (touchSrcWrap) touchSrcWrap.classList.remove('dragging');
                if (touchLastTarget) touchLastTarget.classList.remove('drag-over');
                touchSrcIndex = null; touchSrcWrap = null; touchLastTarget = null;
            });
        }

        function positionnerGhost(touch) {
            ghost.style.left = (touch.clientX - 60) + 'px';
            ghost.style.top  = (touch.clientY - 60) + 'px';
        }

        function deplacerVignette(srcIndex, destIndex) {
            const movedFile = orderedFiles.splice(srcIndex, 1)[0];
            orderedFiles.splice(destIndex, 0, movedFile);
            const movedBlob = compressedBlobs.splice(srcIndex, 1)[0];
            compressedBlobs.splice(destIndex, 0, movedBlob);
            const wraps   = Array.from(preview.children);
            const srcWrap = wraps[srcIndex];
            const dstWrap = wraps[destIndex];
            if (srcIndex < destIndex) preview.insertBefore(srcWrap, dstWrap.nextSibling);
            else                      preview.insertBefore(srcWrap, dstWrap);
            rafraichirNumeros();
        }

        function rafraichirNumeros() {
            Array.from(preview.children).forEach((wrap, i) => {
                wrap.dataset.index = i;
                wrap.querySelector('.thumb-num').textContent = i + 1;
            });
        }

        async function chargerMiniature(file, imgEl, spinnerEl) {
            const ext = file.name.split('.').pop().toLowerCase();
            if (ext === 'heic') {
                const fd = new FormData();
                fd.append('file', file);
                try {
                    const r = await fetch('/preview', { method: 'POST', body: fd });
                    if (r.ok) imgEl.src = URL.createObjectURL(await r.blob());
                } catch(e) { imgEl.alt = 'HEIC'; }
            } else {
                imgEl.src = URL.createObjectURL(file);
            }
            imgEl.onload  = () => { spinnerEl.remove(); imgEl.style.display = ''; };
            imgEl.onerror = () => { spinnerEl.remove(); imgEl.style.display = ''; imgEl.alt = '?'; };
        }

        function creerVignette(file, index) {
            const wrap = document.createElement('div');
            wrap.className = 'thumb-wrap';
            wrap.dataset.index = index;
            const num = document.createElement('div');
            num.className = 'thumb-num';
            num.textContent = index + 1;
            const spinner = document.createElement('div');
            spinner.className = 'thumb-spinner';
            const img = document.createElement('img');
            img.style.display = 'none';
            wrap.appendChild(num);
            wrap.appendChild(spinner);
            wrap.appendChild(img);
            const sizeMB = file.size / (1024 * 1024);
            if (sizeMB > LIMIT_MB) {
                const warn = document.createElement('div');
                warn.className = 'thumb-warn';
                warn.textContent = sizeMB.toFixed(0) + ' Mo — fichier lourd';
                wrap.appendChild(warn);
            }
            chargerMiniature(file, img, spinner);
            ajouterDragSouris(wrap);
            ajouterDragTactile(wrap);
            return wrap;
        }

        async function construirePreview(files) {
            preview.innerHTML = '';
            orderedFiles    = files;
            compressedBlobs = new Array(files.length).fill(null);
            files.forEach((file, i) => preview.appendChild(creerVignette(file, i)));
            countEl.textContent = files.length + ' photo(s) sélectionnée(s)';
            countEl.className = 'ok';
            btn.disabled = false;
            compressedBlobs = await preCompresserTout(files);
        }

        input.addEventListener('change', () => {
            if (input.files.length > 0) {
                construirePreview(Array.from(input.files));
            } else {
                orderedFiles = []; compressedBlobs = [];
                preview.innerHTML = '';
                countEl.textContent = 'Aucune photo sélectionnée';
                countEl.className = '';
                btn.disabled = true;
            }
        });

        document.getElementById('form').addEventListener('submit', async (e) => {
            e.preventDefault();
            btn.disabled = true;
            status.textContent = '';
            status.className = '';
            progWrap.style.display = 'block';
            progBar.style.width = '10%';
            progLabel.textContent = 'Envoi des photos...';

            const formData = new FormData();
            formData.append('titre', document.getElementById('titre').value);
            formData.append('description', document.getElementById('description').value);
            formData.append('esp_notes', document.getElementById('esp_notes').value);
            formData.append('numerotation', document.getElementById('numerotation').checked ? '1' : '0');
            formData.append('max3parligne', document.getElementById('max3parligne').checked ? '1' : '0');
            formData.append('ajustertaille', document.getElementById('ajustertaille').checked ? '1' : '0');

            orderedFiles.forEach((file, i) => {
                const blob = compressedBlobs[i];
                const ext = file.name.split('.').pop().toLowerCase();
                const nom = ext === 'heic' ? file.name.slice(0, -4) + 'jpg' : file.name;
                formData.append('photos', blob || file, nom);
            });

            const steps = [
                [30, 'Mise en page...'],
                [60, 'Construction du PDF...'],
                [85, 'Finalisation...'],
            ];
            let stepIdx = 0;
            const ticker = setInterval(() => {
                if (stepIdx < steps.length) {
                    const [target, label] = steps[stepIdx++];
                    progBar.style.width = target + '%';
                    progLabel.textContent = label;
                }
            }, 1200);

            try {
                const response = await fetch('/generer', { method: 'POST', body: formData });
                clearInterval(ticker);
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.erreur || 'Erreur inconnue');
                }
                progBar.style.width = '100%';
                progLabel.textContent = 'Téléchargement...';
                const blob  = await response.blob();
                const titre = document.getElementById('titre').value.replace(/[^a-zA-Z0-9]/g, '_') || 'Album';
                const url   = URL.createObjectURL(blob);
                const a     = document.createElement('a');
                a.href = url; a.download = titre + '.pdf'; a.click();
                URL.revokeObjectURL(url);
                status.textContent = 'PDF généré et téléchargé !';
                status.className = 'success';
            } catch (err) {
                clearInterval(ticker);
                status.textContent = 'Erreur : ' + err.message;
                status.className = 'error';
            } finally {
                btn.disabled = false;
                setTimeout(() => { progWrap.style.display = 'none'; progBar.style.width = '0%'; }, 2000);
            }
        });
    </script>
</body>
</html>
"""


# --- Polices ---

def _chemins_windows(nom_fichier):
    chemins = [f"C:/Windows/Fonts/{nom_fichier}"]
    local_app = os.environ.get('LOCALAPPDATA')
    if local_app:
        chemins.append(os.path.join(local_app, "Microsoft", "Windows", "Fonts", nom_fichier))
    return chemins


def _installer_police_windows(chemin_src, nom_fichier):
    import shutil
    try:
        import winreg
    except ImportError:
        return None
    local_app = os.environ.get('LOCALAPPDATA')
    if not local_app:
        return None
    dossier_dest = Path(local_app) / "Microsoft" / "Windows" / "Fonts"
    dossier_dest.mkdir(parents=True, exist_ok=True)
    chemin_dest = dossier_dest / nom_fichier
    try:
        shutil.copy2(chemin_src, chemin_dest)
        cle = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cle, 0, winreg.KEY_SET_VALUE) as reg:
            winreg.SetValueEx(reg, nom_fichier.replace('.ttf', ' (TrueType)'), 0, winreg.REG_SZ, str(chemin_dest))
        print(f"Police installée dans {chemin_dest}")
        return str(chemin_dest)
    except Exception as e:
        print(f"Installation automatique impossible : {e}")
        return None


def trouver_police(nom_fichier, candidats_systeme, urls_telechargement):
    dest = Path.home() / nom_fichier
    if dest.exists():
        return str(dest)
    for c in candidats_systeme:
        if Path(c).exists():
            return str(Path(c))
    print(f"{nom_fichier} introuvable, téléchargement en cours...")
    for url in urls_telechargement:
        try:
            urllib.request.urlretrieve(url, dest)
            if dest.exists() and dest.stat().st_size > 10000:
                print("Téléchargement réussi.")
                if platform.system() == "Windows":
                    chemin_installe = _installer_police_windows(dest, nom_fichier)
                    if chemin_installe:
                        try:
                            dest.unlink()
                        except Exception:
                            pass
                        return chemin_installe
                return str(dest)
        except Exception as e:
            print(f"  Échec ({url}) : {e}")
        if dest.exists():
            dest.unlink(missing_ok=True)
    raise RuntimeError(
        f"Impossible de trouver ou télécharger {nom_fichier}.\n"
        "Sur Android/Termux : pkg install fonts-dejavu\n"
        "Sur Windows : placez le fichier dans C:\\Windows\\Fonts\\ "
        "ou %LocalAppData%\\Microsoft\\Windows\\Fonts\\"
    )


def trouver_dejavu():
    return trouver_police(
        "DejaVuSans.ttf",
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/data/data/com.termux/files/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/data/data/com.termux/files/usr/share/fonts/DejaVuSans.ttf",
        ] + _chemins_windows("DejaVuSans.ttf"),
        [
            "https://raw.githubusercontent.com/matplotlib/matplotlib/main/lib/matplotlib/mpl-data/fonts/ttf/DejaVuSans.ttf",
            "https://raw.githubusercontent.com/prawnpdf/prawn/master/data/fonts/DejaVuSans.ttf",
        ]
    )


def trouver_noto_emoji():
    return trouver_police(
        "NotoEmoji-Regular.ttf",
        [
            "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
            "/usr/share/fonts/noto/NotoEmoji-Regular.ttf",
            "/data/data/com.termux/files/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
            "/data/data/com.termux/files/usr/share/fonts/NotoEmoji-Regular.ttf",
        ] + _chemins_windows("NotoEmoji-Regular.ttf"),
        [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf",
        ]
    )


POLICE_PATH       = None
POLICE_EMOJI_PATH = None


# --- Détection emoji ---

EMOJI_RANGES = [
    (0x2600,  0x27FF), (0x2B00,  0x2BFF),
    (0x1F300, 0x1F5FF), (0x1F600, 0x1F64F),
    (0x1F680, 0x1F6FF), (0x1F700, 0x1F77F),
    (0x1F900, 0x1F9FF), (0x1FA00, 0x1FAFF),
    (0x231A,  0x231B),  (0x23E9,  0x23F3),
    (0x25AA,  0x25FE),  (0x2614,  0x2615),
    (0x2648,  0x2653),  (0x267F,  0x267F),
    (0x2693,  0x2693),  (0x26A1,  0x26A1),
    (0x26AA,  0x26AB),  (0x26BD,  0x26BE),
    (0x26C4,  0x26C5),  (0x26D4,  0x26D4),
    (0x26EA,  0x26EA),  (0x26F2,  0x26F3),
    (0x26F5,  0x26F5),  (0x26FA,  0x26FA),
    (0x26FD,  0x26FD),
]


def est_emoji(char):
    cp = ord(char)
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)


def segmenter_texte(texte):
    if not texte:
        return []
    segments  = []
    buf       = ""
    buf_emoji = False
    for char in texte:
        c_emoji = est_emoji(char)
        if c_emoji != buf_emoji and buf:
            segments.append((buf, buf_emoji))
            buf = ""
        buf      += char
        buf_emoji = c_emoji
    if buf:
        segments.append((buf, buf_emoji))
    return segments


# --- Logique PDF ---

def nettoyer_texte(texte):
    if not texte:
        return ""
    remp = {
        '\u2018': "'", '\u2019': "'", '\u00ab': '"', '\u00bb': '"',
        '\u2014': '-', '\u2013': '-', '\u2026': '...', '\u20ac': 'EUR'
    }
    for c, r in remp.items():
        texte = texte.replace(c, r)
    return texte


def compresser_image(source, qualite=65, max_px=1200):
    if hasattr(source, 'stream'):
        source.stream.seek(0)
        img_src = source.stream
    else:
        img_src = source
    with Image.open(img_src) as img:
        img = img.convert("RGB")
        if max(img.size) > max_px:
            img.thumbnail((max_px, max_px), Image.LANCZOS)
        w_px, h_px = img.size
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=qualite, optimize=True)
        buf.seek(0)
        return buf, w_px / h_px if h_px != 0 else 1.0


class GenerateurPDF(FPDF):
    def __init__(self, police_path, police_emoji_path):
        super().__init__()
        self.add_font("DejaVu",    "",  police_path)
        self.add_font("DejaVu",    "B", police_path)
        self.add_font("NotoEmoji", "",  police_emoji_path)
        self.set_font("DejaVu", "", 12)

    def ecrire_mixte(self, texte, taille_texte, gras=False):
        taille_emoji = taille_texte + 2
        style = "B" if gras else ""
        for contenu, is_emoji in segmenter_texte(texte):
            if is_emoji:
                self.set_font("NotoEmoji", "", taille_emoji)
            else:
                self.set_font("DejaVu", style, taille_texte)
            self.write(taille_texte * 0.4, contenu)

    def header_premiere_page(self, titre, description, esp_lignes):
        self.set_y(4)
        if any(est_emoji(c) for c in titre):
            self.set_x(self.l_margin)
            self.ecrire_mixte(titre, 18, gras=True)
            self.ln(12)
        else:
            self.set_font("DejaVu", "B", 18)
            self.cell(0, 12, titre, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(esp_lignes)
        if description.strip():
            for ligne in description.split('\n'):
                self.set_x(self.l_margin)
                if ligne.strip():
                    self.ecrire_mixte(ligne, 10)
                self.ln(5)
            self.ln(esp_lignes)
        return self.get_y()

    def pied_de_page(self, numero, limite_bas):
        self.set_font("DejaVu", "", 8)
        self.set_text_color(120)
        self.set_xy(0, limite_bas + 1)
        self.cell(210, 4, f"— {numero} —", align='C')
        self.set_text_color(0)


def traiter_image(args):
    index, fs = args
    try:
        buf, ratio = compresser_image(fs)
        return index, buf, ratio
    except Exception:
        return index, None, 1.0


def simuler_pages(ratios, hauteur, esp_notes, max3parligne, marge_fixe, y_depart, limite_bas):
    ESP_INTER     = 2
    largeur_utile = 210 - (2 * marge_fixe)
    pages         = 1
    y             = y_depart
    idx           = 0
    n_images      = len(ratios)

    while idx < n_images:
        max_n = min(3, n_images - idx) if max3parligne else (n_images - idx)
        n = 1
        for n_essai in range(max_n, 0, -1):
            larg_essai = [hauteur * r for r in ratios[idx:idx + n_essai]]
            if sum(larg_essai) + (n_essai - 1) * ESP_INTER <= largeur_utile or n_essai == 1:
                n = n_essai
                break
        w_total = sum(hauteur * r for r in ratios[idx:idx + n])
        h_ligne = hauteur * (largeur_utile / w_total) if w_total > largeur_utile else hauteur
        if y + h_ligne > limite_bas:
            pages += 1
            y      = marge_fixe
        y   += h_ligne + esp_notes
        idx += n

    return pages


def construire_pdf(titre, description, fichiers, esp_notes_mm, numerotation,
                   max3parligne=True, ajuster_taille=True):
    global POLICE_PATH, POLICE_EMOJI_PATH
    if POLICE_PATH is None:
        POLICE_PATH = trouver_dejavu()
    if POLICE_EMOJI_PATH is None:
        POLICE_EMOJI_PATH = trouver_noto_emoji()

    HAUTEUR_DEFAUT = 43   # hauteur de base : 4,3 cm
    HAUTEUR_MAX    = 200  # plafond de sécurité pour la boucle d'optimisation
    PALIER         = 5    # pas d'augmentation : 0,5 cm
    ESP_INTER      = 2    # espacement horizontal entre photos (mm)
    marge_fixe     = 10
    esp_notes      = max(0, esp_notes_mm)
    bande_num      = 5 if numerotation else 0
    limite_bas     = 297 - marge_fixe - bande_num

    with ThreadPoolExecutor() as executor:
        resultats = list(executor.map(traiter_image, enumerate(fichiers)))
    resultats.sort(key=lambda x: x[0])
    images_info = [(buf, ratio) for _, buf, ratio in resultats if buf is not None]

    if not images_info:
        raise ValueError("Aucune image valide.")

    pdf = GenerateurPDF(POLICE_PATH, POLICE_EMOJI_PATH)
    pdf.set_auto_page_break(False)
    pdf.set_left_margin(marge_fixe)
    pdf.set_right_margin(marge_fixe)

    largeur_utile = 210 - (2 * marge_fixe)
    page_num  = 0
    restantes = list(images_info)

    def nouvelle_page(premiere=False):
        nonlocal page_num
        pdf.add_page()
        page_num += 1
        if premiere:
            return pdf.header_premiere_page(
                nettoyer_texte(titre),
                nettoyer_texte(description),
                3
            )
        return marge_fixe

    y_depart_reel = nouvelle_page(premiere=True)

    # --- Calcul de la hauteur optimale (simulation) ---
    if ajuster_taille:
        ratios    = [r for _, r in images_info]
        pages_ref = simuler_pages(
            ratios, HAUTEUR_DEFAUT, esp_notes, max3parligne,
            marge_fixe, y_depart_reel, limite_bas
        )
        hauteur_choisie = HAUTEUR_DEFAUT
        h_courant       = HAUTEUR_DEFAUT

        # Boucle bornée par HAUTEUR_MAX pour éviter toute boucle infinie
        while h_courant < HAUTEUR_MAX:
            h_candidat     = h_courant + PALIER
            pages_candidat = simuler_pages(
                ratios, h_candidat, esp_notes, max3parligne,
                marge_fixe, y_depart_reel, limite_bas
            )
            if pages_candidat > pages_ref:
                break
            hauteur_choisie = h_candidat
            h_courant       = h_candidat
    else:
        hauteur_choisie = HAUTEUR_DEFAUT

    HAUTEUR_FIXE = hauteur_choisie

    # --- Hauteur de référence basée sur les vrais ratios moyens ---
    # Utilisée comme plafond pour les lignes incomplètes (< max photos)
    # afin qu'elles ne soient jamais disproportionnées.
    ratios_tous    = [r for _, r in images_info]
    ratio_moyen    = sum(ratios_tous) / len(ratios_tous)
    w_ligne_pleine = 3 * ratio_moyen * HAUTEUR_FIXE + 2 * ESP_INTER
    if w_ligne_pleine > largeur_utile:
        h_reference = HAUTEUR_FIXE * (largeur_utile / w_ligne_pleine)
    else:
        h_reference = HAUTEUR_FIXE

    y_actuel = y_depart_reel

    while restantes:
        max_n = min(3, len(restantes)) if max3parligne else len(restantes)

        n = 1
        for n_essai in range(max_n, 0, -1):
            larg_essai = [HAUTEUR_FIXE * r for _, r in restantes[:n_essai]]
            if sum(larg_essai) + (n_essai - 1) * ESP_INTER <= largeur_utile or n_essai == 1:
                n = n_essai
                break

        groupe      = restantes[:n]
        largeurs_th = [HAUTEUR_FIXE * r for _, r in groupe]
        w_total_th  = sum(largeurs_th)

        if w_total_th > largeur_utile:
            # Ligne trop large (panorama) : on réduit proportionnellement
            # sans impacter la hauteur des autres lignes
            h_ligne = HAUTEUR_FIXE * (largeur_utile / w_total_th)
        else:
            # Ligne normale ou incomplète : plafonnée à h_reference
            # pour éviter qu'une dernière ligne seule ne soit géante
            h_ligne = min(HAUTEUR_FIXE, h_reference)

        # Recalcul des largeurs avec la hauteur finale
        ratio_final  = h_ligne / HAUTEUR_FIXE
        largeurs     = [w * ratio_final for w in largeurs_th]
        w_total_reel = sum(largeurs)

        if n == 1:
            esp_reel = 0
            x_depart = marge_fixe + (largeur_utile - w_total_reel) / 2
        else:
            esp_reel = (largeur_utile - w_total_reel) / (n - 1)
            x_depart = marge_fixe

        if y_actuel + h_ligne > limite_bas:
            if numerotation:
                pdf.pied_de_page(page_num, limite_bas)
            y_actuel = nouvelle_page()

        x_actuel = x_depart
        for i, (buf, _) in enumerate(groupe):
            restantes.pop(0)
            try:
                buf.seek(0)
                pdf.image(buf, x=x_actuel, y=y_actuel, w=largeurs[i], h=h_ligne)
            except Exception:
                pass
            x_actuel += largeurs[i] + esp_reel

        y_actuel += h_ligne + esp_notes

    if numerotation:
        pdf.pied_de_page(page_num, limite_bas)

    out = io.BytesIO()
    pdf.output(out)
    out.seek(0)
    return out


# --- Routes Flask ---

@app.route('/')
def index():
    return HTML.replace('__VERSION__', VERSION)


@app.route('/preview', methods=['POST'])
def preview():
    f = request.files.get('file')
    if not f:
        return '', 400
    if not HEIF_DISPONIBLE:
        return jsonify({'erreur': 'pillow-heif non installé — HEIC non supporté'}), 501
    try:
        with Image.open(f.stream) as img:
            img = img.convert("RGB")
            img.thumbnail((300, 300), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            buf.seek(0)
        return Response(buf.read(), mimetype='image/jpeg')
    except Exception as e:
        return jsonify({'erreur': str(e)}), 500


@app.route('/generer', methods=['POST'])
def generer():
    titre          = request.form.get('titre', '').strip()
    description    = request.form.get('description', '').strip()
    fichiers       = request.files.getlist('photos')
    numerotation   = request.form.get('numerotation',   '0') == '1'
    max3parligne   = request.form.get('max3parligne',   '1') == '1'
    ajuster_taille = request.form.get('ajustertaille',  '1') == '1'

    try:
        esp_notes_mm = int(request.form.get('esp_notes', '16'))
    except (ValueError, TypeError):
        esp_notes_mm = 16

    if not titre:
        return jsonify({'erreur': 'Le titre est obligatoire.'}), 400
    if not fichiers or fichiers[0].filename == '':
        return jsonify({'erreur': 'Sélectionnez au moins une photo.'}), 400

    try:
        pdf_buf = construire_pdf(
            titre, description, fichiers,
            esp_notes_mm, numerotation, max3parligne, ajuster_taille
        )
        nom_fichier = "".join(
            c for c in titre if c.isalnum() or c in (' ', '_')
        ).strip().replace(' ', '_') or 'Album'

        return send_file(
            pdf_buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{nom_fichier}.pdf"
        )
    except Exception as e:
        return jsonify({'erreur': str(e)}), 500


# --- Lancement cross-platform ---

PORT = 8080
HOST = "localhost"
URL  = f"http://{HOST}:{PORT}"


def port_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((HOST, PORT)) != 0


def ouvrir_navigateur():
    systeme = platform.system()
    if systeme == "Windows":
        os.startfile(URL)
    elif systeme == "Linux":
        subprocess.Popen(
            ["am", "start", "-a", "android.intent.action.VIEW", "-d", URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    else:
        subprocess.Popen(["open", URL])


if __name__ == "__main__":
    import threading

    POLICE_PATH       = trouver_dejavu()
    POLICE_EMOJI_PATH = trouver_noto_emoji()

    est_termux = (
        os.path.exists("/data/data/com.termux") or
        "com.termux" in os.environ.get("PREFIX", "")
    )

    systeme    = platform.system()
    deja_actif = not port_libre()

    if deja_actif:
        if not est_termux:
            ouvrir_navigateur()
    else:
        if systeme == "Windows":
            t = threading.Thread(
                target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False),
                daemon=True
            )
            t.start()
            for _ in range(10):
                time.sleep(1)
                if not port_libre():
                    break
            ouvrir_navigateur()
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nServeur arrêté.")
        else:
            if not est_termux:
                t = threading.Thread(target=ouvrir_navigateur)
                t.daemon = True
                t.start()
            app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
