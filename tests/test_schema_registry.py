import os
import unittest
import utils
import time
import string
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(CURRENT_DIR, "fixtures", "debian", "schema-registry")
KAFKA_READY = "bash -c 'cub kafka-ready $KAFKA_ZOOKEEPER_CONNECT {brokers} 20 20 10 && echo PASS || echo FAIL'"
HEALTH_CHECK = "bash -c 'cub sr-ready {host} {port} 20 && echo PASS || echo FAIL'"
POST_SCHEMA_CHECK = """curl -X POST -i -H "Content-Type: application/vnd.schemaregistry.v1+json" \
    --data '{"schema": "{\\"type\\": \\"string\\"}"}' \
    %s:%s/subjects/%s/versions"""
GET_SCHEMAS_CHECK = "bash -c 'curl -X GET -i {host}:{port}/subjects'"
ZK_READY = "bash -c 'cub zk-ready {servers} 10 10 2 && echo PASS || echo FAIL'"
KAFKA_CHECK = "bash -c 'kafkacat -L -b {host}:{port} -J' "


class ConfigTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        machine_name = os.environ["DOCKER_MACHINE_NAME"]
        cls.machine = utils.TestMachine(machine_name)

        cls.cluster = utils.TestCluster("config-test", FIXTURES_DIR, "standalone-config.yml")
        cls.cluster.start()

        assert "PASS" in cls.cluster.run_command_on_service("zookeeper", ZK_READY.format(servers="localhost:2181"))
        assert "PASS" in cls.cluster.run_command_on_service("kafka", KAFKA_READY.format(brokers=1))

    @classmethod
    def tearDownClass(cls):
        cls.cluster.shutdown()

    @classmethod
    def is_schema_registry_healthy_for_service(cls, service):
        output = cls.cluster.run_command_on_service(service, HEALTH_CHECK.format(host="localhost", port=8081))
        assert "PASS" in output

    def test_required_config_failure(self):
        self.assertTrue("KAFKASTORE_CONNECTION_URL is required." in self.cluster.service_logs("failing-config", stopped=True))
        self.assertTrue("HOST_NAME is required." in self.cluster.service_logs("failing-config-host-name", stopped=True))

    def test_default_config(self):
        self.is_schema_registry_healthy_for_service("default-config")
        props = self.cluster.run_command_on_service("default-config", "cat /etc/schema-registry/schema-registry.properties")
        expected = """kafkastore.connection.url=zookeeper:2181/defaultconfig
                host.name=default-config
            """
        self.assertEquals(props.translate(None, string.whitespace), expected.translate(None, string.whitespace))

    def test_default_logging_config(self):
        self.is_schema_registry_healthy_for_service("default-config")

        log4j_props = self.cluster.run_command_on_service("default-config", "cat /etc/schema-registry/log4j.properties")
        expected_log4j_props = """log4j.rootLogger=INFO, stdout

            log4j.appender.stdout=org.apache.log4j.ConsoleAppender
            log4j.appender.stdout.layout=org.apache.log4j.PatternLayout
            log4j.appender.stdout.layout.ConversionPattern=[%d] %p %m (%c)%n

            """
        self.assertEquals(log4j_props.translate(None, string.whitespace), expected_log4j_props.translate(None, string.whitespace))


class StandaloneNetworkingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cluster = utils.TestCluster("standalone-network-test", FIXTURES_DIR, "standalone-network.yml")
        cls.cluster.start()
        assert "PASS" in cls.cluster.run_command_on_service("zookeeper-bridge", ZK_READY.format(servers="localhost:2181"))
        assert "PASS" in cls.cluster.run_command_on_service("zookeeper-host", ZK_READY.format(servers="localhost:32181"))
        assert "PASS" in cls.cluster.run_command_on_service("kafka-bridge", KAFKA_READY.format(brokers=1))
        assert "PASS" in cls.cluster.run_command_on_service("kafka-host", KAFKA_READY.format(brokers=1))

    @classmethod
    def tearDownClass(cls):
        cls.cluster.shutdown()

    @classmethod
    def is_schema_registry_healthy_for_service(cls, service):
        output = cls.cluster.run_command_on_service(service, HEALTH_CHECK.format(host="localhost", port=8081))
        assert "PASS" in output

    def test_bridged_network(self):
        # Test from within the container
        self.is_schema_registry_healthy_for_service("schema-registry-bridge")
        # Test from outside the container on host network
        logs = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=HEALTH_CHECK.format(host="localhost", port=18081),
            host_config={'NetworkMode': 'host'})

        self.assertTrue("PASS" in logs)

        # Test from outside the container on bridge network
        logs_2 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=HEALTH_CHECK.format(host="schema-registry-bridge", port=8081),
            host_config={'NetworkMode': 'standalone-network-test_zk'})

        self.assertTrue("PASS" in logs_2)

    def test_host_network(self):
        # Test from within the container
        self.is_schema_registry_healthy_for_service("schema-registry-host")
        # Test from outside the container
        logs = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=HEALTH_CHECK.format(host="localhost", port=8081),
            host_config={'NetworkMode': 'host'})

        self.assertTrue("PASS" in logs)


class ClusterBridgedNetworkTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cluster = utils.TestCluster("cluster-bridged-test", FIXTURES_DIR, "cluster-bridged-plain.yml")
        cls.cluster.start()
        assert "PASS" in cls.cluster.run_command_on_service("zookeeper-1", ZK_READY.format(servers="zookeeper-1:2181,zookeeper-2:2181,zookeeper-3:2181"))
        assert "PASS" in cls.cluster.run_command_on_service("zookeeper-2", ZK_READY.format(servers="zookeeper-1:2181,zookeeper-2:2181,zookeeper-3:2181"))
        assert "PASS" in cls.cluster.run_command_on_service("zookeeper-3", ZK_READY.format(servers="zookeeper-1:2181,zookeeper-2:2181,zookeeper-3:2181"))
        assert "PASS" in cls.cluster.run_command_on_service("kafka-1", KAFKA_READY.format(brokers=1))
        assert "PASS" in cls.cluster.run_command_on_service("kafka-2", KAFKA_READY.format(brokers=1))
        assert "PASS" in cls.cluster.run_command_on_service("kafka-3", KAFKA_READY.format(brokers=1))

    @classmethod
    def tearDownClass(cls):
        cls.cluster.shutdown()

    @classmethod
    def is_schema_registry_healthy_for_service(cls, service):
        output = cls.cluster.run_command_on_service(service, HEALTH_CHECK.format(host="localhost", port=8081))
        assert "PASS" in output

    def test_bridged_network(self):
        # Test from within the container
        self.is_schema_registry_healthy_for_service("schema-registry-1")
        self.is_schema_registry_healthy_for_service("schema-registry-2")
        self.is_schema_registry_healthy_for_service("schema-registry-3")

        # Test from outside the container on bridge network
        logs_1 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=HEALTH_CHECK.format(host="schema-registry-1", port=8081),
            host_config={'NetworkMode': 'cluster-bridged-test_zk'})
        self.assertTrue("PASS" in logs_1)

        logs_2 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=HEALTH_CHECK.format(host="schema-registry-2", port=8081),
            host_config={'NetworkMode': 'cluster-bridged-test_zk'})

        self.assertTrue("PASS" in logs_2)

        logs_3 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=HEALTH_CHECK.format(host="schema-registry-3", port=8081),
            host_config={'NetworkMode': 'cluster-bridged-test_zk'})

        self.assertTrue("PASS" in logs_3)

        # Test writing a schema on SR instance 1
        schema_name_1 = "are-unicorns-real-1"
        logs_4 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=POST_SCHEMA_CHECK % ("schema-registry-1", 8081, schema_name_1),
            host_config={'NetworkMode': 'cluster-bridged-test_zk'})

        self.assertTrue("id" in logs_4)

        # Test reading all schemas and checking for the one we created
        logs_5 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=GET_SCHEMAS_CHECK.format(host="schema-registry-1", port=8081),
            host_config={'NetworkMode': 'cluster-bridged-test_zk'})

        self.assertTrue(schema_name_1 in logs_5)

        # Test writing a schema to SR instance 2
        schema_name_2 = "are-unicorns-real-2"
        logs_6 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=POST_SCHEMA_CHECK % ("schema-registry-2", 8081, schema_name_2),
            host_config={'NetworkMode': 'cluster-bridged-test_zk'})

        self.assertTrue("id" in logs_6)

        # Test reading all schemas and checking for the one we created
        logs_7 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=GET_SCHEMAS_CHECK.format(host="schema-registry-2", port=8081),
            host_config={'NetworkMode': 'cluster-bridged-test_zk'})

        self.assertTrue(schema_name_2 in logs_7)

        # Test writing a schema to SR instance 3
        schema_name_3 = "are-unicorns-real-3"
        logs_8 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=POST_SCHEMA_CHECK % ("schema-registry-3", 8081, schema_name_3),
            host_config={'NetworkMode': 'cluster-bridged-test_zk'})

        self.assertTrue("id" in logs_8)

        # Test reading all schemas and checking for the one we created
        logs_9 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=GET_SCHEMAS_CHECK.format(host="schema-registry-3", port=8081),
            host_config={'NetworkMode': 'cluster-bridged-test_zk'})

        self.assertTrue(schema_name_3 in logs_9)


class ClusterHostNetworkTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cluster = utils.TestCluster("cluster-host-test", FIXTURES_DIR, "cluster-host-plain.yml")
        cls.cluster.start()
        assert "PASS" in cls.cluster.run_command_on_service("zookeeper-1", ZK_READY.format(servers="localhost:22181,localhost:32181,localhost:42181"))
        assert "PASS" in cls.cluster.run_command_on_service("zookeeper-2", ZK_READY.format(servers="localhost:22181,localhost:32181,localhost:42181"))
        assert "PASS" in cls.cluster.run_command_on_service("zookeeper-3", ZK_READY.format(servers="localhost:22181,localhost:32181,localhost:42181"))
        assert "PASS" in cls.cluster.run_command_on_service("kafka-1", KAFKA_READY.format(brokers=1))
        assert "PASS" in cls.cluster.run_command_on_service("kafka-2", KAFKA_READY.format(brokers=1))
        assert "PASS" in cls.cluster.run_command_on_service("kafka-3", KAFKA_READY.format(brokers=1))

    @classmethod
    def tearDownClass(cls):
        cls.cluster.shutdown()

    @classmethod
    def is_schema_registry_healthy_for_service(cls, service):
        output = cls.cluster.run_command_on_service(service, HEALTH_CHECK.format(host="localhost", port=8081))
        assert "PASS" in output

    def test_host_network(self):
        # Test from within the container
        self.is_schema_registry_healthy_for_service("schema-registry-1")
        self.is_schema_registry_healthy_for_service("schema-registry-2")
        self.is_schema_registry_healthy_for_service("schema-registry-3")
        # Test from outside the container
        logs_1 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=HEALTH_CHECK.format(host="localhost", port=8081),
            host_config={'NetworkMode': 'host'})

        self.assertTrue("PASS" in logs_1)

        logs_2 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=HEALTH_CHECK.format(host="localhost", port=8082),
            host_config={'NetworkMode': 'host'})

        self.assertTrue("PASS" in logs_2)

        logs_3 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=HEALTH_CHECK.format(host="localhost", port=8083),
            host_config={'NetworkMode': 'host'})

        self.assertTrue("PASS" in logs_3)

        # Test writing a schema to SR instance 1
        schema_name_1 = "are-unicorns-real-1"
        logs_4 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=POST_SCHEMA_CHECK % ("localhost", 8081, schema_name_1),
            host_config={'NetworkMode': 'host'})

        self.assertTrue("id" in logs_4)

        # Test reading all schemas and checking for the one we created
        logs_5 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=GET_SCHEMAS_CHECK.format(host="localhost", port=8081),
            host_config={'NetworkMode': 'host'})

        self.assertTrue(schema_name_1 in logs_5)

        # Test writing a schema to SR instance 2
        schema_name_2 = "are-unicorns-real-2"
        logs_6 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=POST_SCHEMA_CHECK % ("localhost", 8082, schema_name_2),
            host_config={'NetworkMode': 'host'})

        self.assertTrue("id" in logs_6)

        # Test reading all schemas and checking for the one we created
        logs_7 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=GET_SCHEMAS_CHECK.format(host="localhost", port=8082),
            host_config={'NetworkMode': 'host'})

        self.assertTrue(schema_name_2 in logs_7)

        # Test writing a schema to SR instance 3
        schema_name_3 = "are-unicorns-real-3"
        logs_8 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=POST_SCHEMA_CHECK % ("localhost", 8083, schema_name_3),
            host_config={'NetworkMode': 'host'})

        self.assertTrue("id" in logs_8)

        # Test reading all schemas and checking for the one we created
        logs_9 = utils.run_docker_command(
            image="confluentinc/cp-schema-registry",
            command=GET_SCHEMAS_CHECK.format(host="localhost", port=8083),
            host_config={'NetworkMode': 'host'})

        self.assertTrue(schema_name_3 in logs_9)
