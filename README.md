docker_test_runner
==================

`docker_test_runner` is a Python wrapper which gives the possibility to build
Docker images and run Docker containers from a single image with different
environment settings.

Of course you can do the same with Docker or Docker-Compose but it was somehow
to complicate to archive the following goals easily:

- Run multiple containers from one image
- Run multiple containers at the same time (without docker-compose) - with
  different environment settings
- On the fly (thread) limits for build processes or containers runs
  (possible via `COMPOSE_PARALLEL_LIMIT` in docker-compose)
- A lean yml-based configuration
- Display a final summary

Requirements
------------

This role requires [Docker](https://www.docker.com), Python 2.7 and some
additional pip packages.

The required pip packages are defined in the
[requirements.txt](requirements.txt) file and can be installed easily via

```sh
pip install -r requirements.txt
```

`docker_test_runner` is tested on Linux and Mac OS and won't run on Python 3.x.

Install
-------

In this repository you can find an [install.sh](install.sh) script which will
install all requirements and download the latest version of the script itself.

```sh
curl https://raw.githubusercontent.com/timorunge/docker-test-runner/master/install.sh | sh
```

Configuration
-------------

The configuration is (hopefully) self explaining. Take a look at the
[docker_test_runner.yml](docker_test_runner.yml) file. Which is also used
for self-testing.

In the [testing section](#testing) you can find some explenation about
the entire workflow.

```yaml
# Select a project name. This is just used for Docker images.
project_name: dtr

# The amount of threads to use.
# Can be overridden by the command line.
threads: 4

# Set log level.
# Valid: CRITICAL, DEBUG, ERROR, INFO, NOTSET, WARNING
# Can be overridden by the command line.
log_level: INFO

# Completely disable logging.
# Can be overridden by the command line.
disable_logging: False

# Build arguments (referenced also in the Dockerfiles)
docker_image_build_args:
  ansible_role: timorunge.docker_test_runner
  ansible_version: "2.6.4"

# Path to the directory containing the Dockerfile(s)
# `__PATH__` is the directory where `docker_test_runner.py` is stored.
# docker_test_runner will automatically replace `__PATH__` with the
# current working directory.
docker_image_path: __PATH__/docker

# Images names for the build context of the Dockerfile(s)
# Images must be stored in the `docker_image_path` folder.
# Images must be named in the following format: Dockerfile_`image_name`.
docker_images:
  - CentOS_7
  - Debian_9_4
  - Debian_10
  - Ubuntu_16_04
  - Ubuntu_17_10
  - Ubuntu_18_04
  - Ubuntu_18_10

# Remove intermediate containers after a successful build.
# Default value is `True`
docker_remove_images: True

# Environment variables to set inside the container.
# Each environment will run in a separate container.
# You have the possiblity to skip container runs based on an environment.
# Simply use the option `skip_images` as a list inside the environment itself.
docker_container_environments:
  env_1:
    injected_dict: { "foo": "bar" }
    injected_list: [ "foo", "bar" ]
    injected_variable: "foo_bar"
    override_variable: "FOO_BAR"
  env_2:
    injected_dict: { "alice": "bob" }
    injected_list: [ "alice", "bob" ]
    injected_variable: "alice_bob"
    override_variable: "ALICE_BOB"
    skip_images:
      - Debian_10
      - Ubuntu_18_10
  env_3:
    injected_dict: { "x": "y" }
    injected_list: [ "x", "y" ]
    injected_variable: "x_y"
    override_variable: "X_Y"

# Configure volumes mounted inside the container.
# `__PATH__` is the directory where `docker_test_runner.py` is stored.
# docker_test_runner will automatically replace `__PATH__` with the
# current working directory.
docker_container_volumes:
  "__PATH__/ansible":
    bind: /etc/ansible/roles/timorunge.docker_test_runner
    mode: ro
  "__PATH__/ansible/tests":
    bind: /ansible
    mode: rw
  "__PATH__/docker":
    bind: /docker
    mode: ro
```

CLI options
-----------

```sh
usage: docker_test_runner.py [-h] [-f FILE] [-t THREADS] [--build-only]
                             [--log-level LOG_LEVEL] [--disable-logging] [-v]

Build Docker images and run containers in different environments.

optional arguments:
  -h, --help            show this help message and exit
  -f FILE, --file FILE  Specify an alternate configuration file.
                        (default: docker_test_runner.yml)
  -t THREADS, --threads THREADS
                        The amount of threads to use.
                        (default: 2)
  --build-only          Build Docker images. Don't start Docker containers.
  --log-level LOG_LEVEL
                        Set log level.
                        Valid: CRITICAL, DEBUG, ERROR, INFO, NOTSET, WARNING
                        (default: INFO)
  --disable-logging     Completely disable logging.
  -v, --version         Display version information.
```

Testing
-------

[![Build Status](https://travis-ci.org/timorunge/docker-test-runner.svg?branch=master)](https://travis-ci.org/timorunge/docker-test-runner)

Tests are done with [Docker](https://www.docker.com) and the
`docker_test_runner` itself.

The tests are creating the following Docker images:

* CentOS 7
* Debian 9.4 (Stretch)
* Debian 10 (Buster)
* Ubuntu 16.04 (Xenial Xerus)
* Ubuntu 17.10 (Artful Aardvark)
* Ubuntu 18.04 (Bionic Beaver)
* Ubuntu 18.10 (Cosmic Cuttlefish)

Ansible is getting installed in a version which is defined as an build argument
of the Docker file. This is set in the `docker_image_build_args` section of
[docker_test_runner.yml](docker_test_runner.yml).

After the build process `docker_test_runner` will start Containers and execute -
as defined in the Dockerfile -
[docker-entrypoint.sh](docker/docker-entrypoint.sh). Here we have access
to the variables which we've set in the `docker_container_environments` section
of the [docker_test_runner.yml](docker_test_runner.yml) configuration.

The environment variables are passed to the Ansible playbook and can be used
like normal variables (setting not defined variables, overriding defaults etc.).

```sh
# Testing or trying everything locally:
./docker_test_runner.py
```

License
-------
BSD

Author Information
------------------

- Timo Runge
