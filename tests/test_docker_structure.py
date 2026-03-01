"""
Docker container structure verification tests.
These tests verify the Dockerfile and container structure without requiring full dependencies.
"""
import os
import unittest


class TestDockerfileStructure(unittest.TestCase):
    """Test Dockerfile structure and configuration"""
    
    def setUp(self):
        # Path to agent-container directory from tests directory
        self.agent_container_dir = os.path.join(
            os.path.dirname(__file__), 
            "..",
            "agent-container"
        )
        self.dockerfile_path = os.path.join(
            self.agent_container_dir,
            "Dockerfile"
        )
    
    def test_dockerfile_exists(self):
        """Test that Dockerfile exists"""
        self.assertTrue(os.path.exists(self.dockerfile_path))
    
    def test_dockerfile_exposes_port_8080(self):
        """Test that Dockerfile exposes port 8080"""
        with open(self.dockerfile_path, 'r') as f:
            content = f.read()
        self.assertIn("EXPOSE 8080", content)
    
    def test_dockerfile_uses_python_base(self):
        """Test that Dockerfile uses Python base image"""
        with open(self.dockerfile_path, 'r') as f:
            content = f.read()
        self.assertIn("FROM python:", content)
    
    def test_dockerfile_copies_server_py(self):
        """Test that Dockerfile copies server.py"""
        with open(self.dockerfile_path, 'r') as f:
            content = f.read()
        self.assertIn("COPY agent-container/server.py", content)
    
    def test_dockerfile_copies_openclaw_json(self):
        """Test that Dockerfile copies openclaw.json"""
        with open(self.dockerfile_path, 'r') as f:
            content = f.read()
        self.assertIn("COPY agent-container/openclaw.json", content)
    
    def test_dockerfile_does_not_copy_deleted_files(self):
        """Test that Dockerfile does not reference deleted multi-tenant files"""
        with open(self.dockerfile_path, 'r') as f:
            content = f.read()
        
        # Verify deleted files are not referenced
        self.assertNotIn("permissions.py", content)
        self.assertNotIn("observability.py", content)
        self.assertNotIn("safety.py", content)
        self.assertNotIn("identity.py", content)
        self.assertNotIn("memory.py", content)
        self.assertNotIn("auth-agent", content)
    
    def test_dockerfile_runs_server_py(self):
        """Test that Dockerfile CMD runs server.py"""
        with open(self.dockerfile_path, 'r') as f:
            content = f.read()
        self.assertIn('CMD ["python", "server.py"]', content)


class TestRequiredFiles(unittest.TestCase):
    """Test that required files exist"""
    
    def setUp(self):
        # Path to agent-container directory from tests directory
        self.container_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "agent-container"
        )
    
    def test_server_py_exists(self):
        """Test that server.py exists"""
        path = os.path.join(self.container_dir, "server.py")
        self.assertTrue(os.path.exists(path))
    
    def test_openclaw_json_exists(self):
        """Test that openclaw.json exists"""
        path = os.path.join(self.container_dir, "openclaw.json")
        self.assertTrue(os.path.exists(path))
    
    def test_requirements_txt_exists(self):
        """Test that requirements.txt exists"""
        path = os.path.join(self.container_dir, "requirements.txt")
        self.assertTrue(os.path.exists(path))
    
    def test_dockerfile_exists(self):
        """Test that Dockerfile exists"""
        path = os.path.join(self.container_dir, "Dockerfile")
        self.assertTrue(os.path.exists(path))
    
    def test_deleted_files_do_not_exist(self):
        """Test that deleted multi-tenant files do not exist"""
        deleted_files = [
            "permissions.py",
            "observability.py",
            "safety.py",
            "identity.py",
            "memory.py"
        ]
        
        for filename in deleted_files:
            path = os.path.join(self.container_dir, filename)
            self.assertFalse(
                os.path.exists(path),
                f"File {filename} should have been deleted"
            )


class TestRequirementsTxt(unittest.TestCase):
    """Test requirements.txt structure"""
    
    def setUp(self):
        # Path to agent-container directory from tests directory
        self.requirements_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "agent-container",
            "requirements.txt"
        )
    
    def test_requirements_has_requests(self):
        """Test that requirements.txt includes requests"""
        with open(self.requirements_path, 'r') as f:
            content = f.read()
        self.assertIn("requests", content)
    
    def test_requirements_has_boto3(self):
        """Test that requirements.txt includes boto3 for S3 persistence"""
        with open(self.requirements_path, 'r') as f:
            content = f.read()
        self.assertIn("boto3", content)
    
    def test_requirements_minimal(self):
        """Test that requirements.txt is minimal (no multi-tenant dependencies)"""
        with open(self.requirements_path, 'r') as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
        # Should only have requests and boto3
        self.assertEqual(len(lines), 2, "requirements.txt should only have 2 dependencies")


class TestOpenClawJson(unittest.TestCase):
    """Test openclaw.json configuration"""
    
    def setUp(self):
        # Path to agent-container directory from tests directory
        self.config_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "agent-container",
            "openclaw.json"
        )
    
    def test_openclaw_json_has_gateway_section(self):
        """Test that openclaw.json has gateway configuration"""
        import json
        with open(self.config_path, 'r') as f:
            config = json.load(f)
        
        self.assertIn("gateway", config)
        self.assertIn("mode", config["gateway"])
        self.assertEqual(config["gateway"]["mode"], "local")
    
    def test_openclaw_json_has_http_endpoints(self):
        """Test that openclaw.json has HTTP endpoint configuration"""
        import json
        with open(self.config_path, 'r') as f:
            config = json.load(f)
        
        self.assertIn("http", config["gateway"])
        self.assertIn("endpoints", config["gateway"]["http"])
        self.assertIn("chatCompletions", config["gateway"]["http"]["endpoints"])
    
    def test_openclaw_json_is_valid_json(self):
        """Test that openclaw.json is valid JSON"""
        import json
        with open(self.config_path, 'r') as f:
            try:
                config = json.load(f)
                self.assertIsInstance(config, dict)
            except json.JSONDecodeError as e:
                self.fail(f"openclaw.json is not valid JSON: {e}")


if __name__ == "__main__":
    unittest.main()
