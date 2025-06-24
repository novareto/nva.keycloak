.. This README is meant for consumption by humans and pypi. Pypi can render rst files so please do not use Sphinx features.
   If you want to learn more about writing documentation, please check out: http://docs.plone.org/about/documentation_styleguide.html
   This text does not appear on pypi or github. It is a comment.

============
nva.keycloak
============

Dieses AddOn für das CMS Plone implementiert den API-Contract für das Service Provider Interface (SPI) von Nico Köbler. 

Features
--------

- Health-Check
- Create User
- Update User
- Check Credentials
- Update Credentials


Installation
------------

Install nva.keycloak by adding it to your buildout::

    [buildout]

    ...

    eggs =
        nva.keycloak


and then running ``bin/buildout``


Contribute
----------

- Issue Tracker: https://github.com/novareto/nva.keycloak/issues
- Source Code: https://github.com/novareto/nva.keycloak


Support
-------

Lars Walther (lwalther@novareto.de)

License
-------

The project is licensed under the MIT.
