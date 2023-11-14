# Changelog

## 0.2.0 - TBD

+ Added support for `import_*` tasks
  + Requires Ansible 2.17 due to changes in how it exposes these tasks
  + These tasks act like `include_*` in that they are part of the stack frame
  + It is not possible to edit the module or task vars for these tasks due to how they run

## 0.1.0 - 2023-11-13

Initial release of `ansibug`

This version should be treated as a pre-release, any behavior may change in future versions depending on feedback.
