#!/usr/bin/env python2
# coding: utf-8


"""
DOCUMENTATION
---
script: docker_test_runner
author: "Timo Runge (@timorunge)"
short_description: `docker_test_runner` is a Python wrapper which gives the possibility to build
                    Docker images and run Docker containers from a single image with different
                    environment settings.
description:
    Of course you can do the same with Docker or Docker-Compose but it was somehow
    to complicate to archive the following goals easily:

    - Run mutliple containers from one image
    - Run mutliple containers at the same time (without docker-compose) - with
    different environment settings
    - On the fly (thread) limits for build processes or containers runs
    (possible via `COMPOSE_PARALLEL_LIMIT` in docker-compose)
    - A lean yml-based configuration
    - Display a final summary
"""


from __future__ import print_function
from argparse import ArgumentParser, RawTextHelpFormatter
import os
import logging
import string
import random
from threading import Thread, BoundedSemaphore
from Queue import Queue
from time import time
from json import dumps
from yaml import load
import colorlog
import docker


__version__ = "0.1.0"
__title__ = 'docker_test_runner'


# Generic classes


class Color(object):
    """ Generate color codes, print them directly or get the message string """

    def __init__(self):
        self.colors = {
            "blue": "4",
            "cyan": "6",
            "green": "2",
            "magenta": "5",
            "red": "1",
            "white": "15",
            "yellow": "3"
        }
        self.end = "m"
        self.esc = "\x1b["
        self.start_code = self.esc + "38;5;"

    def cprint(self, message, color):
        """ Print message colored """
        print(self.message_string(message, color))

    def message_string(self, message, color):
        """ Return the colored formatted message string """
        return "{}{}{}".format(self.code(color), message, self.reset())

    def code(self, color):
        """ Generate color code """
        return "{}{}{}".format(self.start_code, self.colors[color], self.end)

    def get_colors(self):
        """ Get all colors """
        return self.colors.keys()

    def reset(self):
        """ Reset color code """
        return "{}0{}".format(self.esc, self.end)


class SearchAndReplace(object):
    """ Class to mange search and replace operations """

    def __init__(self, search, replace):
        self.replace = replace
        self.search = search

    def in_dict(self, obj):
        """ Search and replace keys and values in a dictionary """
        for key in obj.keys():
            if self.search in key:
                new_key = string.replace(key, self.search, self.replace)
                obj[new_key] = obj.pop(key)
        for key, value in obj.items():
            if self.search in value:
                obj[key] = string.replace(value, self.search, self.replace)
            if isinstance(value, dict):
                obj[key] = self.in_dict(value)
        return obj

    def in_str(self, obj):
        """ Search and replace values in a string """
        return obj.replace(self.search, self.replace)


class Time(object):
    """ Basic time operations """

    def __init__(self, start):
        self.start = start
        self.delta = time() - self.start

    def delta_in_hms(self):
        """ Get time detla in a human readable format """
        hours = int(self.delta / (60 * 60))
        minutes = int((self.delta % (60 * 60)) / 60)
        seconds = self.delta % 60
        return "{}h {:>02}m {:>05.2f}s".format(hours, minutes, seconds)

    def delta_in_s(self):
        """ Get time delta in seconds """
        return "{:>05.2f}s".format(self.delta)


# Docker specific classes


class Configuration(object):
    """ Get and set the configuration for the Docker Test Runner """

    def __init__(self, config_file):
        self.config = dict({})
        self.config_file = config_file
        self.path = os.path.dirname(os.path.abspath(__file__))
        self._from_file()
        self._validate()

    def add(self, section, key, value):
        """ Add a key value pair to a section """
        self.config[section][key] = value

    def add_section(self, section, obj):
        """ Get an entire section """
        self.config[section] = obj

    def get_all(self):
        """ Get the entire configuration """
        return self.config

    def get_key(self, key):
        """ Get one key """
        return self.config[key]

    def get_section(self, section):
        """ Get an entire section """
        return self.config[section]

    def get_section_key(self, section, key):
        """ Get one section key """
        return self.config[section][key]

    def _from_file(self):
        try:
            _logger().debug("Reading configuration file.")
            with open("%s" % (self.config_file), "r") as config_file:
                _logger().debug("Replacing __PATH__ with \"%s\" in configuration file.", self.path)
                self.config = SearchAndReplace("__PATH__", self.path).in_dict(load(config_file))
        except IOError as error:
            _logger().exception("Error while reading configuration file.")
            raise error

    def _validate(self):
        _logger().debug("Validating configuration file.")
        required_keys = ["docker_image_build_args", "docker_image_path", "docker_images"]
        optional_keys = ["docker_container_environments", "docker_container_volumes"]
        _logger().debug("Checking for required configuration keys.")
        for required_key in required_keys:
            if not self.config.has_key(required_key):
                message = "Required configuration key \"%s\" is missing." % (required_key)
                _logger().exception(message)
                raise Exception(message)
        _logger().debug("Checking for optional configuration keys.")
        for optional_key in optional_keys:
            if not self.config.has_key(optional_key):
                _logger().debug("Optional configuration key \"%s\" is missing.", optional_key)
                _logger().debug("Adding empty dict for \"%s\".", optional_key)
                self.add_section(optional_key, dict({}))


class DockerContainers(object):
    """ Create container configuration and give the possibility to run them """

    def __init__(self, semaphore, config, images):
        self.config = config
        self.containers = dict({})
        self.images = images
        self.queue = Queue()
        self.semaphore = semaphore
        self._containers()

    def run(self):
        """ Run the containers """
        threads = []
        for docker_container, docker_container__configuration in self.containers.iteritems():
            run_docker_container = _RunDockerContainer(
                self.semaphore, \
                self.queue, \
                docker_container, \
                docker_container__configuration
                )
            run_docker_container.start()
            threads.append(run_docker_container)
        for thread in threads:
            thread.join()

    def get(self, container):
        """
        Get container information for specific container
        """
        return self.get_all()[container]

    def get_all(self):
        """
        Get container information for all containers
        """
        while not self.queue.empty():
            self.containers.update(self.queue.get())
        return self.containers

    def info(self):
        """
        Display complete container information
        """
        print(dumps(self.get_all(), indent=4, sort_keys=True))

    def _containers(self):
        """ Create the container run configuration """
        self.containers = dict({})
        for image in self.images.iterkeys():
            if self.config.has_key("docker_container_environments"):
                _logger().debug("Create environment based container information.")
                for env, env_settings in self.config["docker_container_environments"].iteritems():
                    name = "%s_%s_%s" % (
                        image,
                        env,
                        "".join(
                            random.choice(string.ascii_letters + string.digits)
                            for _ in range(6)
                            )
                        )
                    self.containers[name] = dict({})
                    self.containers[name]["environment"] = env_settings
                    self.containers[name]["image"] = self.images[image]["image"]
                    self.containers[name]["messages"] = list([])
                    if self.config.has_key("docker_container_volumes"):
                        self.containers[name]["volumes"] = self.config["docker_container_volumes"]
            else:
                _logger().debug("Create container information. No environments set.")
                name = "%s_%s" % (
                    image,
                    "".join(
                        random.choice(string.ascii_letters + string.digits)
                        for _ in range(6)
                        )
                    )
                self.containers[name] = dict({})
                self.containers[name]["image"] = self.images[image]["image"]
                self.containers[name]["messages"] = list([])
                if self.config.has_key("docker_container_volumes"):
                    self.containers[name]["volumes"] = self.config["docker_container_volumes"]


class _RunDockerContainer(Thread):

    def __init__(self, semaphore, queue, name, container):
        super(_RunDockerContainer, self).__init__()
        self.color = random.choice(Color().get_colors())
        self.container = container
        self.name = name
        self.queue = queue
        self.semaphore = semaphore
        self.start_time = time()

    def run(self):
        self.semaphore.acquire()
        try:
            self._run_container()
        finally:
            self.queue.put({"%s" % (self.name): self.container})
            self.semaphore.release()

    def _run_container(self):
        try:
            _logger().info("Starting container %s...", (self.name))
            container = _docker_client().containers.run(
                self.container["image"], \
                detach=True, \
                environment=self.container["environment"], \
                name=self.name, \
                remove=True, \
                stderr=True, \
                stdout=True, \
                volumes=self.container["volumes"]
                )
            for line in container.logs(stream=True):
                _logger().info(Color().message_string("%s" % (line.strip()), self.color))
            self.container["exit_code"] = int(container.wait()["StatusCode"])
            if self.container["exit_code"] == 0:
                log_message = "Container {} run succeeded. [Duration: {}]" \
                    .format(self.name, Time(self.start_time).delta_in_hms())
                _logger().info(log_message)
                self.container["messages"].append(log_message)
            else:
                log_message = "Container {} run failed. [Duration: {}]" \
                    .format(self.name, Time(self.start_time).delta_in_hms())
                _logger().error(log_message)
                self.container["exit_code"] = 1
                self.container["messages"].append(log_message)
        except (
                docker.errors.ContainerError, \
                docker.errors.ImageNotFound, \
                docker.errors.APIError
            ) as error:
            log_message = "Container {} run failed. [Duration: {}]" \
                .format(self.name, Time(self.start_time).delta_in_hms())
            _logger().error(log_message)
            self.container["exit_code"] = 1
            self.container["messages"].append(log_message)
            raise error


class DockerImages(object):
    """ Create Docker images """

    def __init__(self, semaphore, config):
        self.config = config
        self.images = dict({})
        self.queue = Queue()
        self.semaphore = semaphore

    def get(self, image):
        """
        Get image information for specific container
        """
        return self.get_all()[image]

    def get_all(self):
        """
        Get all information about the generated images
        """
        while not self.queue.empty():
            self.images.update(self.queue.get())
        return self.images

    def info(self):
        """
        Display complete image information
        """
        print(dumps(self.get_all(), indent=4, sort_keys=True))

    def run(self):
        """ Run Docker image creation """
        threads = []
        for docker_image in self.config["docker_images"]:
            build_docker_image = _BuildDockerImage(
                self.semaphore, \
                self.queue, \
                docker_image, \
                self.config
                )
            build_docker_image.start()
            threads.append(build_docker_image)
        for thread in threads:
            thread.join()


class _BuildDockerImage(Thread):

    def __init__(self, semaphore, queue, name, config):
        super(_BuildDockerImage, self).__init__()
        self.config = config
        self.image = dict({})
        self.name = name
        self.queue = queue
        self.semaphore = semaphore
        self.start_time = time()

    def run(self):
        self.semaphore.acquire()
        try:
            self._build()
        finally:
            self.queue.put(self.image)
            self.semaphore.release()

    def _build(self):
        _logger().debug("Starting image build process.")
        dockerfile = "%s/Dockerfile_%s" % (self.config["docker_image_path"], self.name)
        self.image[self.name] = dict({})
        self.image[self.name]["messages"] = list([])
        _logger().debug("Using Dockerfile: %s", (dockerfile))
        try:
            _logger().info("Build %s image...", (self.name))
            _logger().debug(
                "Build information:\nbuildargs: %s\ndockerfile: %s\npath: %s", \
                self.config["docker_image_build_args"],
                dockerfile,
                self.config["docker_image_path"]
                )
            image, build_logs = _docker_client().images.build(
                buildargs=self.config["docker_image_build_args"], \
                dockerfile=dockerfile, \
                path=self.config["docker_image_path"]
                )
            del build_logs
            _logger().debug("ID of image %s: %s", self.name, image.short_id)
            self.image[self.name]["image"] = image.short_id
            log_message = "{} image created. [Duration: {}]" \
                .format(self.name, Time(self.start_time).delta_in_hms())
            _logger().info(log_message)
            self.image[self.name]["messages"].append(log_message)
        except (
                docker.errors.BuildError, \
                docker.errors.APIError, \
                TypeError
            ) as error:
            log_message = "Build image {} failed. [Duration: {}]" \
                .format(self.name, Time(self.start_time).delta_in_hms())
            _logger().error(log_message)
            self.image[self.name]["messages"].append(log_message)
            raise error


def _docker_client():
    """ Get the Docker client """
    try:
        _logger().debug("Creating Docker connection.")
        docker_client = docker.from_env()
        return docker_client
    except docker.errors.DockerException as error:
        _logger().exception("Can not communicate to the Docker server.")
        raise error


def _logger(log_level="INFO", disable=False):
    try:
        log_level = logging.getLevelName(log_level)
        log_format = "%(log_color)s[%(levelname)s] %(threadName)s:%(reset)s %(message)s"
        colorlog.basicConfig(level=log_level, format=log_format)
        logger = colorlog.getLogger(__name__)
        if disable:
            # @TODO: Fix message: No handlers could be found for logger "__main__"
            logger.propagate = False
        return logger
    except Exception as error:
        _logger().exception("Can not set log level: %s is not valid.", log_level)
        raise error


def _semaphore(value=2):
    try:
        _logger().debug("Setting thread limit to: %s", value)
        value = int(value)
        semaphore = BoundedSemaphore(value)
        return semaphore, value
    except ValueError as error:
        _logger().exception("Can not set thread limit: %s is not an integer.", value)
        raise error


def _run(start_time, args):
    """ Run the Docker test runner """

    exit_code = [0]

    _logger(args.log_level, args.disable_logging)

    semaphore, threads = _semaphore(args.threads)

    _logger().info("Using %s threads", (threads))

    __config = Configuration(args.config_file)
    if os.environ.has_key("TRAVIS"):
        __config.add("docker_image_build_args", "TRAVIS", os.environ.get("TRAVIS"))
        os.environ.update(__config.get_section("docker_image_build_args"))
    config = __config.get_all()

    __docker_images = DockerImages(semaphore, config)
    __docker_images.run()
    docker_images = __docker_images.get_all()

    if not args.build_only:
        __docker_containers = DockerContainers(semaphore, config, docker_images)
        __docker_containers.run()
        docker_containers = __docker_containers.get_all()

    _logger().info("Summary:")
    for items in docker_images.itervalues():
        for message in items["messages"]:
            _logger().info(message)
    if not args.build_only:
        for items in docker_containers.itervalues():
            exit_code.append(items["exit_code"])
            for message in items["messages"]:
                _logger().info(message)
    _logger().info("Threads: %s", (threads))
    _logger().info("Images: %s", (len(docker_images)))
    _logger().info("Containers: %s", (len(docker_containers)))
    _logger().info("Total duration: %s", (Time(start_time).delta_in_hms()))

    exit(sum(exit_code))


def main():
    """ Build Docker images and run containers in different environments. """
    start_time = time()

    parser = ArgumentParser(
        description="Build Docker images and run containers in different environments.", \
        formatter_class=RawTextHelpFormatter
        )
    parser.add_argument(
        "-f", \
        "--file", \
        default="docker_test_runner.yml", \
        dest="config_file", \
        metavar="FILE", \
        help="Specify an alternate configuration file.\n(default: docker_test_runner.yml)"
        )
    parser.add_argument(
        "-t", \
        "--threads", \
        default=2, \
        dest="threads", \
        help="The amount of threads to use.\n(default: 2)"
        )
    parser.add_argument(
        "--build-only", \
        action="store_true", \
        dest="build_only", \
        help="Build Docker images. Don't start Docker containers."
        )
    parser.add_argument(
        "--log-level", \
        default="INFO", \
        dest="log_level", \
        help="Set log level.\nValid: CRITICAL, DEBUG, ERROR, INFO, NOTSET, WARNING\n(default: INFO)"
        )
    parser.add_argument(
        "--disable-logging", \
        action="store_true", \
        default=False, \
        dest="disable_logging", \
        help="Completely disable logging."
        )
    parser.add_argument(
        "-v", \
        "--version", \
        action="store_true", \
        dest="version", \
        help="Display version information."
        )
    args = parser.parse_args()

    if args.version:
        print(__version__)
        exit(0)

    _run(start_time, args)


if __name__ == "__main__":
    main()
