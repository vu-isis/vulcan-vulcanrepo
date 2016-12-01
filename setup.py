# -*- coding: utf-8 -*-
try:
    from setuptools import setup, find_packages
except ImportError:
    from ez_setup import use_setuptools
    use_setuptools()
    from setuptools import setup, find_packages

from vulcanrepo import __version__

PROJECT_DESCRIPTION = '''
VulcanRepo implements the Repository Layer for VulcanForge.
'''

setup(
    name='VulcanRepo',
    version=__version__,
    description='Base distribution of the VulcanRepo development platform',
    long_description=PROJECT_DESCRIPTION,
    author='Vanderbilt ISIS',
    author_email='',
    url='',
    keywords='vehicleforge vulcanforge turbogears pylons jinja2 mongodb',
    license='Apache License, http://www.apache.org/licenses/LICENSE-2.0',
    platforms=['Linux', 'MacOS X'],
    classifiers=[
        'Framework :: Pylons',
        'Framework :: TurboGears',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 2.7',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Framework',
        'License :: OSI Approved :: Apache Software License',
    ],
    install_requires=[
        "VulcanForge",
        "GitPython"
    ],
    setup_requires=["PasteScript >= 1.7"],
    paster_plugins=[
        'PasteScript', 'Pylons', 'TurboGears2', 'tg.devtools', 'Ming'],
    packages=find_packages(exclude=['ez_setup']),
    test_suite='nose.collector',
    tests_require=[
        'WebTest >= 1.2', 'BeautifulSoup < 4.0', 'pytidylib', 'poster', 'nose'],
    message_extractors={
        'vulcanforge': [
            ('**.py', 'python', None),
            ('templates/**.mako', 'mako', None),
            ('templates/**.html', 'jinja', None),
            ('static/**', 'ignore', None)]
    },
    entry_points="""
    [paste.paster_command]
    sync_commit_hooks = vulcanrepo.command:SyncCommitHooks
    add_repo_visualizer_hook = vulcanrepo.command:AddRepoVisualizerHook

    """
)

