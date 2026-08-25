from setuptools import setup

setup(
    name="pythonFS",
    options={
        'build_apps': {
            'include_patterns': [
                '**/*.py',
                '**/*.wav',
                '**/*.pkl',
                'audio_cache/**',
                'audio_assets/**',
                'osm_raw_cache/**',
            ],
            'exclude_patterns': [
                '**/__pycache__/**',
                '.venv*/**',
                '.git/**',
            ],
            'gui_apps': {'pythonFS': 'main.py'},
            'plugins': ['pandagl', 'p3openal_audio'],
            'platforms': ['win_amd64'],
            'requirements_path': './requirements.txt',
        }
    }
)