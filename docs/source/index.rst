Welcome to pylm's documentation!
================================

.. only:: html

    .. image:: https://badge.fury.io/py/pylm.svg
        :target: https://badge.fury.io/py/pylm
    
    .. image:: https://img.shields.io/badge/docs-latest-brightgreen.svg?style=flat
        :target: https://pylm.readthedocs.io/en/latest
    
    .. image:: https://badge.fury.io/gh/nfqsolutions%2Fpylm.svg
        :target: https://badge.fury.io/gh/nfqsolutions%2Fpylm

Pylm is the Python implementation of PALM, a framework to build
clusters of high performance backend components. It is presented in two
different levels of abstraction. In the high level API you will find
servers and clients that are functional *out of the box*. Use the high
level API if you are interested in simple communication patterns like
client-server, master-slave or a streaming pipeline. In the low level
API there are a variety of small components that, once combined,
they can be used to implement almost any kind of
component. It's what the high level API uses under the hood. Choose
the low level API if you are interested in creating your custom
component and your custom communication pattern.

.. important::

    Pylm requires a version of Python equal or higher than 3.4, and it is more
    thoroughly tested with Python 3.5.

  
Pylm is released under a dual licensing scheme. The source is released
as-is under the the AGPL version 3 license, a copy of the license is
included with the source. If this license does not suit you,
you can purchase a commercial license from `NFQ Solutions
<http://nfqsolutions.com>`_

Pylm is a project developed by `Guillem Borrell <http://guillemborrell.es>`_
for `NFQ Solutions <http://nfqsolutions.com>`_.


.. toctree::
    :maxdepth: 3

    introduction
    high-level
    low-level
    hl-api-docstrings
    ll-api-docstrings
    examples
    registry
    beyond


Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

This project has been funded by the Spanish Ministry of Economy and
Competitivity under the grant IDI-20150936, cofinanced with FEDER
funds.
