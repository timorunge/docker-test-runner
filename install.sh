#!/bin/sh

curl -sSf https://raw.githubusercontent.com/timorunge/docker-test-runner/master/requirements.txt | pip install -r /dev/stdin
curl -sSfO https://raw.githubusercontent.com/timorunge/docker-test-runner/master/docker_test_runner.py
curl -sSfo docker_test_runner.yml.example https://raw.githubusercontent.com/timorunge/docker-test-runner/master/docker_test_runner.yml
chmod +x docker_test_runner.py
