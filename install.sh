#!/bin/sh

curl -s https://raw.githubusercontent.com/timorunge/docker-test-runner/master/requirements.txt | pip install -r /dev/stdin
curl -sO https://raw.githubusercontent.com/timorunge/docker-test-runner/master/docker_test_runner.py
curl -so docker_test_runner.yml-example https://raw.githubusercontent.com/timorunge/docker-test-runner/master/docker_test_runner.yml
chmod +x docker_test_runner.py
