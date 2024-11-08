# Changelog

## 0.2.0 - TBD

+ Officially support Ansible 2.18 and Python 3.13
+ Drop support for Ansible 2.14 and 2.15 now they are end of life

## 0.1.2 - 2024-07-16

+ Fix properly setting `COLLECTIONS_PATHS` for an `ansibug` run when no explicit config value was provided

## 0.1.1 - 2024-07-08

+ Officially support Ansible 2.17
+ Fix support for `include_*` tasks with Ansible 2.17+
+ Fix up `ansible-config dump` parser when a config entry has no name
  + Entries with no `name` key was added in Ansible 2.18

## 0.1.0 - 2023-11-13

Initial release of `ansibug`

This version should be treated as a pre-release, any behavior may change in future versions depending on feedback.
