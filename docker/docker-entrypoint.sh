#!/bin/sh
set -e

test -z ${override_variable} && echo "Missing environment variable: override_variable" && exit 1

printf "[defaults]\nroles_path=/etc/ansible/roles\n" > ansible.cfg

ansible-lint /ansible/test.yml
ansible-lint /etc/ansible/roles/${ansible_role}/tasks/main.yml

ansible-playbook /ansible/test.yml \
  -i /ansible/inventory \
  --syntax-check

ansible-playbook /ansible/test.yml \
  -i /ansible/inventory \
  --connection=local \
  --become \
  -e "{ injected_dict: ${injected_dict} }" \
  -e "{ injected_list: ${injected_list} }" \
  -e "{ injected_variable: ${injected_variable} }" \
  -e "{ override_variable: ${override_variable} }" \
  $(test -z ${travis} && echo "-vvvv")

ansible-playbook /ansible/test.yml \
  -i /ansible/inventory \
  --connection=local \
  --become \
  -e "{ injected_dict: ${injected_dict} }" \
  -e "{ injected_list: ${injected_list} }" \
  -e "{ injected_variable: ${injected_variable} }" \
  -e "{ override_variable: ${override_variable} }" | \
  grep -q "changed=0.*failed=0" && \
  (echo "Idempotence test: pass" && exit 0) || \
  (echo "Idempotence test: fail" && exit 1)
