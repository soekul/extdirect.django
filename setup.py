from setuptools import setup, find_packages
import os

version = '0.4dev'

setup(name='extdirect.django',
      version=version,
      description="Ext.Direct implementation for Django",
      long_description=open("README.md").read(),
      # Get more strings from http://www.python.org/pypi?%3Aaction=list_classifiers
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Django",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Libraries :: Python Modules",
        ],
      keywords='',
      author='Julien Bouquillon',
      author_email='julien@revolunet.com',
      url='http://github.com/revolunet/extdirect.django/tree/master',
      license='BSD',      
      namespace_packages=['extdirect'],
      packages=find_packages(exclude=['ez_setup']),
      package_data = {
          'extdirect' : [ '*.html', '*.css', '*.js' ]
      },
      test_suite="extdirect.django.tests",
      include_package_data=True,
      zip_safe=False,
      install_requires=[
          'setuptools',
          # -*- Extra requirements: -*-
      ],
      entry_points="""
      # -*- Entry points: -*-
      """,
      )
