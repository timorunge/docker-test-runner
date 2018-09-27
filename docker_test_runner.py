#!/usr/bin/env python2
# coding: utf-8


"""
DOCUMENTATION
---
script: docker_test_runner
author: "Timo Runge (@timorunge)"
short_description: `docker_test_runner` is a Python wrapper which gives the
                    possibility to build Docker images and run Docker
                    containers from a single image with different environment
                    settings.
description:
    Of course you can do the same with Docker or Docker-Compose but it was
    somehow to complicate to archive the following goals easily:

    - Run multiple containers from one image
    - Run multiple containers at the same time (without docker-compose) - with
    different environment settings
    - On the fly (thread) limits for build processes or containers runs
    (possible via `COMPOSE_PARALLEL_LIMIT` in docker-compose)
    - A lean yml-based configuration
    - Display a final summary
"""


from __future__ import print_function
from argparse import ArgumentParser, RawTextHelpFormatter
import os
import fnmatch
import logging
import string
import re
import random
from threading import BoundedSemaphore, Thread, _Verbose
from Queue import Queue
from time import time
from json import dumps
from yaml import load
import colorlog
import docker


__author__ = "Timo Runge"
__copyright__ = "Copyright 2018, Timo Runge"
__email__ = "me@timorunge.com"
__license__ = "BSD"
__maintainer__ = "Timo Runge"
__title__ = "docker_test_runner"
__version__ = "0.0.4"


LOG = colorlog.getLogger(__name__)


# Generic classes


class Color(object):
    """ Generate color codes, print them directly or get the message string """

    def __init__(self):
        self.color_codes = {
            "blue": 4,
            "cyan": 6,
            "green": 2,
            "magenta": 5,
            "red": 1,
            "white": 15,
            "yellow": 3
        }
        self.end = "m"
        self.esc = "\x1b["
        self.start_code = self.esc + "38;5;"

    def colors(self):
        """ Get all colors """
        return self.color_codes.keys()

    def cprint(self, message, color):
        """ Print a colored message """
        print(self.cstring(message, color))

    def cstring(self, message, color):
        """ Return the colored formatted message string """
        return "{}{}{}".format(
            self._code(color),
            message,
            self._reset())

    def _code(self, color):
        """ Generate color code """
        return "{}{}{}".format(
            self.start_code,
            self.color_codes[color],
            self.end)

    def _reset(self):
        """ Reset color code """
        return "{}0{}".format(
            self.esc,
            self.end)


class SearchAndReplace(object):
    """ Class to mange search and replace operations """

    def __init__(self, search, replace):
        self.replace = replace
        self.search = search

    def in_dict(self, obj, regex=False):
        """ Search and replace keys and values in a dictionary """
        if isinstance(obj, dict):
            if bool(obj):
                for key in obj.keys():
                    if isinstance(key, str) and self.search in key:
                        new_key = self.in_str(key, regex)
                        obj[new_key] = obj.pop(key)
                for key, value in obj.items():
                    if isinstance(value, dict):
                        obj[key] = self.in_dict(value, regex)
                    if isinstance(value, str) and self.search in value:
                        obj[key] = self.in_str(value, regex)
            return obj
        else:
            raise TypeError("Object is no valid dictionary.")

    def in_str(self, obj, regex=False):
        """ Search and replace values in a string """
        if not regex:
            return string.replace(obj, self.search, self.replace)
        return re.sub(self.search, self.replace, obj)


class Semaphore(object):
    """ A factory function that returns a new BoundedSemaphore. """

    def __init__(self, threads):
        self._set(threads)

    def set(self, threads):
        """ Set the amount of threads. """
        self._set(threads)

    def get(self):
        """
        Get BoundedSemaphore factory.
        Returns a tuple. The first object is BoundedSemaphore, the second
        item is the thread limit as int.
        """
        return BoundedSemaphore(self.threads), self.threads

    def _set(self, threads):
        try:
            self.threads = int(threads)
        except ValueError as error:
            raise error


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
        self.config_filename = "docker_test_runner.yml"
        self.path = os.path.dirname(os.path.abspath(__file__))
        self._from_file()
        self._validate()

    def add(self, key, value, section=None):
        """ Add a key value pair (to a section) """
        try:
            if section is not None:
                self.config[section][key] = value
            else:
                self.config[key] = value
        except KeyError as error:
            raise error

    def get(self, key=None, section=None):
        """
        Get the entire configuration or define a key
        (with or without section) and get the value.
        """
        if key is not None:
            try:
                if section is not None:
                    return self.config[section][key]
                return self.config[key]
            except KeyError as error:
                raise error
        return self.config

    def _from_file(self):
        try:
            if os.path.isfile(self.config_file):
                _config_file = self.config_file
            else:
                _files = list(
                    _recursive_iglob(
                        self.path,
                        self.config_filename))
                _first_file = next(iter(_files))
                _config_file = _first_file
            with open("%s" % (_config_file), "r") as config_file:
                _yaml = load(config_file)
                self.config = SearchAndReplace(
                    "__PATH__",
                    self.path).in_dict(_yaml)
        except IOError as error:
            raise error

    def _validate(self):
        optional_config_keys = {
            "disable_logging": False,
            "docker_container_environments": dict({}),
            "docker_container_volumes": dict({}),
            "docker_remove_images": True,
            "log_level": "INFO",
            "project_name": None,
            "threads": 2}
        required_config_keys = [
            "docker_image_build_args",
            "docker_image_path",
            "docker_images"]
        for optional_config_key, optional_config_value in \
                optional_config_keys.iteritems():
            if optional_config_key not in self.config:
                self.add(optional_config_key, optional_config_value)
        for required_config_key in required_config_keys:
            if required_config_key not in self.config:
                raise KeyError(
                    "Required configuration key \"%s\" is missing." %
                    required_config_key)


class _DockerThreadedObject(object):

    def __init__(self, semaphore, config, class_instance):
        self.class_instance = class_instance
        self.config = config
        self.objects = dict({})
        self.queue = Queue()
        self.semaphore = semaphore

    def get(self, obj=None):
        """ Get object informations (for an specific object) """
        self._wait_for_queue()
        if obj is not None:
            try:
                return self.objects[obj]
            except KeyError as error:
                raise error
        return self.objects

    def info(self):
        """ Display complete object information """
        print(dumps(self.get(), indent=4, sort_keys=True))

    def run(self):
        """ Start to run the threaded the object class """
        threads = list([])
        for obj, obj_config in self.objects.iteritems():
            run = self.class_instance(
                self.semaphore,
                self.queue,
                obj,
                obj_config)
            run.start()
            threads.append(run)
        for thread in threads:
            thread.join()

    def _wait_for_queue(self):
        while not self.queue.empty():
            self.objects.update(self.queue.get())
        self._validate()

    def _validate(self):
        if not bool(self.objects):
            raise KeyError(
                "%s: Object dictionary is empty." %
                self.__class__.__name__)


class DockerContainers(_DockerThreadedObject):
    """ Create container configuration and give the possibility to run them """

    def __init__(self, semaphore, config, images):
        _DockerThreadedObject.__init__(
            self,
            semaphore,
            config,
            _RunDockerContainer)
        self.images = images
        self._objects()

    def _objects(self):
        """ Create the container run configuration """
        for image in self.images.iterkeys():  # pylint: disable=R1702
            if bool(self.config["docker_container_environments"]):
                LOG.debug("Create environment based container information.")
                for env, env_settings in \
                        self.config["docker_container_environments"]. \
                        iteritems():
                    skip = False
                    if "skip_images" in env_settings:
                        for skip_image in env_settings["skip_images"]:
                            if skip_image == image:
                                LOG.debug(
                                    "Skipping container run for image: %s",
                                    image)
                                skip = True
                    if not skip:
                        _rand = random.SystemRandom().randrange(100000, 999999)
                        container = "%s_%s_%s" % (
                            image,
                            env,
                            _rand)
                        self.objects[container] = dict({})
                        self.objects[container]["environment"] = env_settings
                        self.objects[container]["image"] = \
                            self.images[image]["image"]
                        self.objects[container]["messages"] = list([])
                        if "docker_container_volumes" in self.config:
                            self.objects[container]["volumes"] = \
                                self.config["docker_container_volumes"]
            else:
                LOG.debug("Create container information. No environments set.")
                _rand = random.SystemRandom().randrange(100000, 999999)
                container = "%s_%s" % (
                    image,
                    _rand)
                self.objects[container] = dict({})
                self.objects[container]["environment"] = dict({})
                self.objects[container]["image"] = self.images[image]["image"]
                self.objects[container]["messages"] = list([])
                if "docker_container_volumes" in self.config:
                    self.objects[container]["volumes"] = \
                        self.config["docker_container_volumes"]


class DockerImages(_DockerThreadedObject):
    """ Create Docker images """

    def __init__(self, semaphore, config):
        _DockerThreadedObject.__init__(
            self,
            semaphore,
            config,
            _BuildDockerImage
        )
        self._objects()

    def _objects(self):
        for image in self.config["docker_images"]:
            self.objects[image] = self.config


class _RunDockerContainer(Thread, _Verbose):

    def __init__(self, semaphore, queue, name, config):
        _Verbose.__init__(self)
        Thread.__init__(self)
        self.color = Color()
        self.container = config
        self.name = name
        self.queue = queue
        self.semaphore = semaphore

    def run(self):
        self.semaphore.acquire()
        try:
            self._run_container()
        finally:
            self.queue.put({self.name: self.container})
            self.semaphore.release()

    def _run_container(self):
        start_time = time()
        color = random.SystemRandom().choice(self.color.colors())
        try:
            LOG.info("Starting container %s...", self.name)
            container = _docker_client().containers.run(
                self.container["image"],
                detach=True,
                environment=self.container["environment"],
                name=self.name,
                remove=True,
                stderr=True,
                stdout=True,
                volumes=self.container["volumes"])
            for line in container.logs(stream=True):
                LOG.info(
                    self.color.cstring(
                        line.strip(),
                        color))
            self.container["exit_code"] = int(container.wait()["StatusCode"])
            if self.container["exit_code"] == 0:
                log_message = "Container {} run succeeded. [Duration: {}]". \
                    format(
                        self.name,
                        Time(start_time).delta_in_hms())
                LOG.info(log_message)
                self.container["messages"].append(log_message)
            else:
                log_message = "Container {} run failed. [Duration: {}]". \
                    format(
                        self.name,
                        Time(start_time).delta_in_hms())
                LOG.error(log_message)
                self.container["exit_code"] = 1
                self.container["messages"].append(log_message)
        except (
                docker.errors.ContainerError,
                docker.errors.ImageNotFound,
                docker.errors.APIError) as error:
            log_message = "Container {} run failed. [Duration: {}]". \
                format(
                    self.name,
                    Time(start_time).delta_in_hms())
            LOG.error(log_message)
            self.container["exit_code"] = 1
            self.container["messages"].append(log_message)
            raise error


class _BuildDockerImage(Thread, _Verbose):

    def __init__(self, semaphore, queue, name, config):
        _Verbose.__init__(self)
        Thread.__init__(self)
        self.config = config
        self.image = dict({})
        self.name = name
        self.queue = queue
        self.semaphore = semaphore

    def run(self):
        self.semaphore.acquire()
        try:
            self._build()
        finally:
            self.queue.put({self.name: self.image})
            self.semaphore.release()

    def _build(self):
        start_time = time()
        LOG.debug("Starting image build process.")
        dockerfile = "%s/Dockerfile_%s" % \
            (self.config["docker_image_path"],
             self.name)
        LOG.debug("Using Dockerfile: %s", dockerfile)
        self.image["messages"] = list([])
        try:
            LOG.info("Build %s image...", self.name)
            LOG.debug(
                "Build information:\nbuildargs: %s\ndockerfile: %s\npath: %s",
                self.config["docker_image_build_args"],
                dockerfile,
                self.config["docker_image_path"])
            project_name = None
            _tag = "%s" % self.name
            if self.config["project_name"] is not None:
                project_name = SearchAndReplace(
                    "[^0-9a-zA-Z]+",
                    "_").in_str(
                        self.config["project_name"],
                        True)
                _tag = "%s_%s" % (project_name, self.name)
            tag = _tag.lower()
            image, build_logs = _docker_client().images.build(
                buildargs=self.config["docker_image_build_args"],
                dockerfile=dockerfile,
                path=self.config["docker_image_path"],
                rm=bool(self.config["docker_remove_images"]),
                tag=tag)
            del build_logs
            LOG.debug("ID of image %s: %s", self.name, image.short_id)
            self.image["image"] = image.short_id
            log_message = "{} image created. [Duration: {}]" \
                .format(self.name, Time(start_time).delta_in_hms())
            LOG.info(log_message)
            self.image["exit_code"] = 0
            self.image["messages"].append(log_message)
        except (
                docker.errors.BuildError,
                docker.errors.APIError,
                TypeError) as error:
            log_message = "Build image {} failed. [Duration: {}]" \
                .format(self.name, Time(start_time).delta_in_hms())
            LOG.error(log_message)
            self.image["exit_code"] = 1
            self.image["messages"].append(log_message)
            raise error


def _docker_client():
    try:
        return docker.from_env()
    except docker.errors.DockerException as error:
        raise error


def _logger(log_level="INFO", disable_logging=False):
    try:
        log_level = logging.getLevelName(log_level)
        log_format = ("%(log_color)s[%(levelname)s]"
                      "%(threadName)s:%(reset)s %(message)s")
        colorlog.basicConfig(level=log_level, format=log_format)
        logger = colorlog.getLogger(__name__)
        if disable_logging is True:
            logger.disabled = True
        return logger
    except Exception as error:
        raise error


def _recursive_iglob(root_dir=".", pattern="*"):
    for root, dirs, files in os.walk(root_dir):
        del dirs
        for filename in fnmatch.filter(files, pattern):
            yield os.path.join(root, filename)


def _run(args):  # pylint: disable=R0912,R0914,R0915
    """ Run the Docker test runner """

    def _config(config_file):
        """ Make me nice one day... """
        _config = Configuration(config_file)
        if "TRAVIS" in os.environ:
            _config.add(
                "TRAVIS",
                os.environ.get("TRAVIS"),
                "docker_image_build_args")
        _config = _config.get()
        os.environ.update(_config["docker_image_build_args"])
        if args.disable_logging:
            _disable_logging = args.disable_logging
        elif _config["disable_logging"]:
            _disable_logging = _config["disable_logging"]
        else:
            _disable_logging = False
        if args.log_level:
            _log_level = args.log_level
        elif _config["log_level"]:
            _log_level = _config["log_level"]
        else:
            _log_level = "INFO"
        if args.threads:
            _threads = args.threads
        elif _config["threads"]:
            _threads = _config["threads"]
        else:
            _threads = 2
        _config["disable_logging"] = _disable_logging
        _config["log_level"] = _log_level
        _config["threads"] = _threads
        return _config

    def _objects_messages(name, objects):
        for obj in objects.itervalues():
            if obj["exit_code"] == 0:
                _sucessfull[name] += 1
            _exit_code.append(obj["exit_code"])
            for message in obj["messages"]:
                if obj["exit_code"] == 0:
                    LOG.info(message)
                else:
                    LOG.error(message)

    _exit_code = [0]
    _expected = dict({})
    _start_time = time()
    _sucessfull = dict({})
    _sucessfull["container_runs"] = 0
    _sucessfull["image_runs"] = 0

    config = _config(args.config_file)

    LOG = _logger(  # pylint: disable=C0103,W0621
        config["log_level"],
        config["disable_logging"])

    _semaphore = Semaphore(config["threads"])
    semaphore, threads = _semaphore.get()

    LOG.info("%s Threads", threads)

    _expected["docker_images"] = len(config["docker_images"])
    LOG.info("%s expected images", _expected["docker_images"])
    if not args.build_only:  # pylint: disable=R1702
        if bool(config["docker_container_environments"]):
            _skip = 0
            for _docker_image in config["docker_images"]:
                for _docker_env, _docker_env_settings in \
                        config["docker_container_environments"].iteritems():
                    if "skip_images" in _docker_env_settings:
                        for _skip_image in _docker_env_settings["skip_images"]:
                            if _docker_image == _skip_image:
                                _skip += 1
            _docker_envs = len(config["docker_container_environments"])
            _expected["docker_container_runs"] = (
                _docker_envs *
                _expected["docker_images"]) - _skip
            LOG.info("%s environments", _docker_envs)
            LOG.info(
                "%s expected container runs",
                _expected["docker_container_runs"])
        else:
            _expected["docker_container_runs"] = _expected["docker_images"]
            LOG.info("%s environments", "0")
            LOG.info(
                "%s expected container runs",
                _expected["docker_container_runs"])

    _docker_images = DockerImages(semaphore, config)
    _docker_images.run()
    docker_images = _docker_images.get()

    if not args.build_only:
        _docker_containers = DockerContainers(semaphore, config, docker_images)
        _docker_containers.run()
        docker_containers = _docker_containers.get()

    _summary_msg = "Summary:"
    if config["project_name"] is not None:
        _summary_msg = "Summary for project %s:" % config["project_name"]
    LOG.info(_summary_msg)
    _objects_messages("image_runs", docker_images)
    if not args.build_only:
        _objects_messages("container_runs", docker_containers)
    LOG.info("Threads: %s", threads)
    image_msg = "Images: %s/%s" % \
                (_sucessfull["image_runs"],
                 _expected["docker_images"])
    if _sucessfull["image_runs"] == _expected["docker_images"]:
        LOG.info(image_msg)
    else:
        LOG.error(image_msg)
    if not args.build_only:
        container_msg = "Containers: %s/%s" % \
            (_sucessfull["container_runs"],
             _expected["docker_container_runs"])
        if _sucessfull["container_runs"] == _expected["docker_container_runs"]:
            LOG.info(container_msg)
        else:
            LOG.error(container_msg)
    LOG.info("Total duration: %s", Time(_start_time).delta_in_hms())

    exit_code = sum(_exit_code)
    return exit_code


def _version():
    print(__version__)
    return 0


def main():
    """ Build Docker images and run containers in different environments. """

    parser = ArgumentParser(
        description="Build Docker images and run containers in different"
                    "environments.",
        formatter_class=RawTextHelpFormatter)
    parser.add_argument(
        "-f",
        "--file",
        default="docker_test_runner.yml",
        dest="config_file",
        metavar="FILE",
        help="Specify an alternate configuration file.\n"
             "(default: docker_test_runner.yml - there is a recursive search"
             "for this file. The first one found will be used.)")
    parser.add_argument(
        "-t",
        "--threads",
        dest="threads",
        help="The amount of threads to use.\n"
             "(default: 2)")
    parser.add_argument(
        "--build-only",
        action="store_true",
        dest="build_only",
        help="Build Docker images. Don't start Docker containers.")
    parser.add_argument(
        "--log-level",
        dest="log_level",
        help="Set log level.\n"
             "Valid: CRITICAL, DEBUG, ERROR, INFO, NOTSET, WARNING\n"
             "(default: INFO)")
    parser.add_argument(
        "--disable-logging",
        action="store_true",
        dest="disable_logging",
        help="Completely disable logging.")
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        dest="version",
        help="Display version information.")
    args = parser.parse_args()

    if args.version:
        exit(_version())

    exit(_run(args))


if __name__ == "__main__":
    main()
