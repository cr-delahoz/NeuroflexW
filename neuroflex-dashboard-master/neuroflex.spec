# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None

BASE_DIR = Path(SPECPATH)

a = Analysis(
    ['neuroflex_launcher.py'],
    pathex=[str(BASE_DIR)],
    binaries=collect_dynamic_libs('onnxruntime'),
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('ml/model_artifacts', 'ml/model_artifacts'),
        ('config', 'config'),
        ('accounts', 'accounts'),
        ('dashboard', 'dashboard'),
        ('audit', 'audit'),
        ('reports', 'reports'),
        ('terms', 'terms'),
        ('integrations', 'integrations'),
        ('updater', 'updater'),
        ('offline_mode', 'offline_mode'),
    ],
    hiddenimports=[
        'django',
        'webview',
        'django.contrib.admin',
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.sessions',
        'django.contrib.messages',
        'django.contrib.staticfiles',
        'accounts',
        'dashboard',
        'audit',
        'reports',
        'clinical_sessions',
        'terms',
        'integrations',
        'updater',
        'offline_mode',
        'offline_mode.apps',
        'offline_mode.views',
        'offline_mode.urls',
        'offline_mode.forms',
        'offline_mode.models',
        'offline_mode.decorators',
        'offline_mode.admin',
        'offline_mode.middleware',
        'offline_mode.context_processors',
        'offline_mode.discovery',
        'offline_mode.services.connectivity',
        'offline_mode.services.pairing_service',
        'offline_mode.services.lan_session_service',
        'offline_mode.services.lan_terms_service',
        'offline_mode.services.offline_session_ui_service',
        'offline_mode.services.offline_auth_service',
        'offline_mode.services.sync_service',
        'offline_mode.services.audit_service',
        'offline_mode.services.jwt_utils',
        'offline_mode.services.checksums',
        'offline_mode.api.lan.urls',
        'offline_mode.api.lan.auth',
        'offline_mode.api.lan.sessions',
        'offline_mode.api.lan.pairing',
        'offline_mode.api.lan.terms',
        'ml',
        'onnxruntime',
        'onnxruntime.capi.onnxruntime_pybind11_state',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tensorflow', 'keras', 'sklearn', 'scikit-learn', 'threadpoolctl', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Runtime clinical records belong in NEUROFLEX_DATA_DIR, never in a release.
# PyInstaller's Django hook can also discover the development SQLite database.
private_targets = (
    'clinical_sessions/data/local_sessions/',
    'media/',
    'private_reports/',
)
a.datas = [
    item for item in a.datas
    if not (
        str(item[0]).replace('\\', '/').lower() in {'.env', 'db.sqlite3', 'security-audit.jsonl'}
        or str(item[0]).replace('\\', '/').lower().startswith(private_targets)
    )
]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='neuroflex',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='installer/assets/neuroflex.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='neuroflex',
)
