# Changelog

## 0.3.1 - TBD

+ Added support for Ansible 2.19 which introduced Data Tagging

## 0.3.0 - 2025-02-24

+ Added support for restart with a `Launch` configuration, trying to restart an `Attach` configuration will stop the process but fail to re-attach
+ Added `--temp-dir` option for `python -m ansibug dap ...` to control the temporary directory used for storing the Ansible launch script
+ Added exception breakpoints for:
  + `Uncaught Failures` - Fired when an error is raised in Ansible but is not ignored or rescued
  + `Unreachable Hosts` - Fired when a host is marked as unreachable
  + `Skipped Tasks` - Fired when a task is skipped
+ Stop deprecation message about custom strategy plugins introduced in Ansible 2.19

## 0.2.0 - 2024-11-10

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
