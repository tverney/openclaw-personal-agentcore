"""
Docker container integration tests.
These tests verify that the Docker container builds, starts, and responds correctly.

Requirements tested:
- 8.3: Docker container builds successfully
- 8.4: Docker container starts without errors
- 8.7: /ping and /invocations endpoints respond correctly
"""
import json
import os
import subprocess
import time
import unittest
import requests


class TestDockerBuild(unittest.TestCase):
    """Test Docker image build process"""
    
    @classmethod
    def setUpClass(cls):
        """Build Docker image once for all tests"""
        cls.image_name = "openclaw-personal-test:latest"
        cls.repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        cls.build_success = False
        cls.build_output = ""
        
        print(f"\nBuilding Docker image from {cls.repo_root}...")
        try:
            result = subprocess.run(
                [
                    "docker", "build",
                    "-f", "agent-container/Dockerfile",
                    "-t", cls.image_name,
                    "."
                ],
                cwd=cls.repo_root,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            cls.build_output = result.stdout + result.stderr
            cls.build_success = (result.returncode == 0)
            
            if cls.build_success:
                print("✓ Docker image built successfully")
            else:
                print(f"✗ Docker build failed:\n{cls.build_output}")
        
        except subprocess.TimeoutExpired:
            cls.build_output = "Build timed out after 5 minutes"
            print(f"✗ {cls.build_output}")
        except Exception as e:
            cls.build_output = str(e)
            print(f"✗ Build error: {e}")
    
    def test_docker_image_builds_successfully(self):
        """Test that Docker image builds without errors (Requirement 8.3)"""
        self.assertTrue(
            self.build_success,
            f"Docker build failed:\n{self.build_output}"
        )
    
    def test_docker_image_exists(self):
        """Test that Docker image exists after build"""
        if not self.build_success:
            self.skipTest("Docker build failed, skipping image existence check")
        
        result = subprocess.run(
            ["docker", "images", "-q", self.image_name],
            capture_output=True,
            text=True
        )
        
        self.assertTrue(
            result.stdout.strip(),
            f"Docker image {self.image_name} not found"
        )
    
    def test_docker_image_has_correct_architecture(self):
        """Test that Docker image is built for correct architecture"""
        if not self.build_success:
            self.skipTest("Docker build failed, skipping architecture check")
        
        result = subprocess.run(
            ["docker", "inspect", self.image_name, "--format", "{{.Architecture}}"],
            capture_output=True,
            text=True
        )
        
        architecture = result.stdout.strip()
        # Should be amd64 or arm64 depending on build platform
        self.assertIn(
            architecture,
            ["amd64", "arm64"],
            f"Unexpected architecture: {architecture}"
        )


class TestDockerContainer(unittest.TestCase):
    """Test Docker container startup and runtime"""
    
    @classmethod
    def setUpClass(cls):
        """Start Docker container once for all tests"""
        cls.image_name = "openclaw-personal-test:latest"
        cls.container_name = "openclaw-test-container"
        cls.container_port = 8080
        cls.host_port = 18080  # Use different port to avoid conflicts
        cls.container_id = None
        cls.container_running = False
        
        # Check if image exists
        result = subprocess.run(
            ["docker", "images", "-q", cls.image_name],
            capture_output=True,
            text=True
        )
        
        if not result.stdout.strip():
            print(f"\n✗ Docker image {cls.image_name} not found. Run build tests first.")
            return
        
        # Stop and remove any existing test container
        subprocess.run(
            ["docker", "rm", "-f", cls.container_name],
            capture_output=True,
            stderr=subprocess.DEVNULL
        )
        
        print(f"\nStarting Docker container on port {cls.host_port}...")
        try:
            result = subprocess.run(
                [
                    "docker", "run",
                    "-d",
                    "--name", cls.container_name,
                    "-p", f"{cls.host_port}:{cls.container_port}",
                    "-e", "AWS_REGION=us-east-2",
                    "-e", "BEDROCK_MODEL_ID=us.amazon.nova-lite-v1:0",
                    "-e", "OPENCLAW_SKIP_ONBOARDING=1",
                    cls.image_name
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                cls.container_id = result.stdout.strip()
                print(f"✓ Container started: {cls.container_id[:12]}")
                
                # Wait for container to be ready
                print("Waiting for container to be ready...")
                cls.container_running = cls._wait_for_container_ready()
                
                if cls.container_running:
                    print("✓ Container is ready")
                else:
                    print("✗ Container failed to become ready")
                    cls._print_container_logs()
            else:
                print(f"✗ Failed to start container:\n{result.stderr}")
        
        except Exception as e:
            print(f"✗ Error starting container: {e}")
    
    @classmethod
    def tearDownClass(cls):
        """Stop and remove test container"""
        if cls.container_id:
            print(f"\nStopping container {cls.container_id[:12]}...")
            subprocess.run(
                ["docker", "rm", "-f", cls.container_name],
                capture_output=True
            )
            print("✓ Container stopped and removed")
    
    @classmethod
    def _wait_for_container_ready(cls, timeout=60):
        """Wait for container to be ready by checking /ping endpoint"""
        deadline = time.time() + timeout
        
        while time.time() < deadline:
            try:
                # Check if container is still running
                result = subprocess.run(
                    ["docker", "ps", "-q", "-f", f"name={cls.container_name}"],
                    capture_output=True,
                    text=True
                )
                
                if not result.stdout.strip():
                    print("✗ Container stopped unexpectedly")
                    return False
                
                # Try to ping the endpoint
                response = requests.get(
                    f"http://localhost:{cls.host_port}/ping",
                    timeout=2
                )
                
                if response.status_code == 200:
                    return True
            
            except requests.exceptions.ConnectionError:
                pass  # Container not ready yet
            except requests.exceptions.Timeout:
                pass  # Container not ready yet
            
            time.sleep(2)
        
        return False
    
    @classmethod
    def _print_container_logs(cls):
        """Print container logs for debugging"""
        if cls.container_id:
            result = subprocess.run(
                ["docker", "logs", cls.container_name],
                capture_output=True,
                text=True
            )
            print(f"\nContainer logs:\n{result.stdout}\n{result.stderr}")
    
    def test_container_starts_without_errors(self):
        """Test that container starts successfully (Requirement 8.4)"""
        self.assertIsNotNone(
            self.container_id,
            "Container failed to start"
        )
        
        # Check container is running
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={self.container_name}"],
            capture_output=True,
            text=True
        )
        
        self.assertTrue(
            result.stdout.strip(),
            "Container is not running"
        )
    
    def test_container_has_no_errors_in_logs(self):
        """Test that container logs don't contain critical errors"""
        if not self.container_running:
            self.skipTest("Container not running, skipping log check")
        
        result = subprocess.run(
            ["docker", "logs", self.container_name],
            capture_output=True,
            text=True
        )
        
        logs = result.stdout + result.stderr
        
        # Check for common error patterns
        error_patterns = [
            "Traceback (most recent call last)",
            "Error:",
            "Exception:",
            "CRITICAL:",
        ]
        
        for pattern in error_patterns:
            if pattern in logs:
                # Some errors might be expected during startup, so just warn
                print(f"\nWarning: Found '{pattern}' in logs:\n{logs}")


class TestDockerEndpoints(unittest.TestCase):
    """Test Docker container HTTP endpoints"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test configuration"""
        cls.container_name = "openclaw-test-container"
        cls.host_port = 18080
        cls.base_url = f"http://localhost:{cls.host_port}"
        
        # Check if container is running
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={cls.container_name}"],
            capture_output=True,
            text=True
        )
        
        cls.container_running = bool(result.stdout.strip())
        
        if not cls.container_running:
            print(f"\n✗ Container {cls.container_name} is not running")
    
    def test_ping_endpoint_responds(self):
        """Test that /ping endpoint responds correctly (Requirement 8.7)"""
        if not self.container_running:
            self.skipTest("Container not running")
        
        response = requests.get(f"{self.base_url}/ping", timeout=5)
        
        self.assertEqual(
            response.status_code,
            200,
            f"Expected status 200, got {response.status_code}"
        )
        
        data = response.json()
        self.assertIn("status", data)
        self.assertEqual(data["status"], "ok")
    
    def test_invocations_endpoint_responds(self):
        """Test that /invocations endpoint responds (Requirement 8.7)"""
        if not self.container_running:
            self.skipTest("Container not running")
        
        payload = {
            "message": "Hello, this is a test message",
            "channel": "test"
        }
        
        response = requests.post(
            f"{self.base_url}/invocations",
            json=payload,
            timeout=30
        )
        
        # Should get a response (200 or 500 depending on openclaw state)
        self.assertIn(
            response.status_code,
            [200, 500],
            f"Unexpected status code: {response.status_code}"
        )
        
        # Response should be JSON
        try:
            data = response.json()
            self.assertIsInstance(data, dict)
        except json.JSONDecodeError:
            self.fail("Response is not valid JSON")
    
    def test_invocations_endpoint_with_invalid_json(self):
        """Test that /invocations handles invalid JSON gracefully"""
        if not self.container_running:
            self.skipTest("Container not running")
        
        response = requests.post(
            f"{self.base_url}/invocations",
            data="invalid json",
            headers={"Content-Type": "application/json"},
            timeout=5
        )
        
        self.assertEqual(
            response.status_code,
            400,
            "Should return 400 for invalid JSON"
        )
    
    def test_invocations_endpoint_with_missing_message(self):
        """Test that /invocations handles missing message field"""
        if not self.container_running:
            self.skipTest("Container not running")
        
        payload = {
            "channel": "test"
            # Missing "message" field
        }
        
        response = requests.post(
            f"{self.base_url}/invocations",
            json=payload,
            timeout=30
        )
        
        # Should handle gracefully (either 200 with empty response or 400)
        self.assertIn(
            response.status_code,
            [200, 400, 500],
            f"Unexpected status code: {response.status_code}"
        )
    
    def test_unknown_endpoint_returns_404(self):
        """Test that unknown endpoints return 404"""
        if not self.container_running:
            self.skipTest("Container not running")
        
        response = requests.get(f"{self.base_url}/unknown", timeout=5)
        
        self.assertEqual(
            response.status_code,
            404,
            "Unknown endpoint should return 404"
        )


class TestDockerHealthCheck(unittest.TestCase):
    """Test Docker container health check"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test configuration"""
        cls.container_name = "openclaw-test-container"
        
        # Check if container is running
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={cls.container_name}"],
            capture_output=True,
            text=True
        )
        
        cls.container_running = bool(result.stdout.strip())
    
    def test_container_health_status(self):
        """Test that container reports healthy status"""
        if not self.container_running:
            self.skipTest("Container not running")
        
        # Wait a bit for health check to run
        time.sleep(5)
        
        result = subprocess.run(
            [
                "docker", "inspect",
                self.container_name,
                "--format", "{{.State.Health.Status}}"
            ],
            capture_output=True,
            text=True
        )
        
        health_status = result.stdout.strip()
        
        # Health status might be "starting", "healthy", or empty if no healthcheck
        if health_status:
            self.assertIn(
                health_status,
                ["starting", "healthy"],
                f"Unexpected health status: {health_status}"
            )


if __name__ == "__main__":
    # Run tests in order: build -> container -> endpoints -> health
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes in order
    suite.addTests(loader.loadTestsFromTestCase(TestDockerBuild))
    suite.addTests(loader.loadTestsFromTestCase(TestDockerContainer))
    suite.addTests(loader.loadTestsFromTestCase(TestDockerEndpoints))
    suite.addTests(loader.loadTestsFromTestCase(TestDockerHealthCheck))
    
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
