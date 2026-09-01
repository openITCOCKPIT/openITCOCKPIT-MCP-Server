// Image tags are <openITCOCKPIT version>-<MCP server version>, e.g. 5.6.1-2.0.0.
// VERSION holds the openITCOCKPIT release this build targets; MCP_VERSION holds
// this server's own semantic version, so a fix can ship without openITCOCKPIT
// moving and a pinned tag never changes behaviour underneath a user.
//
// Published per build:
//   <oitc>-<mcp>  immutable, the one to pin
//   <oitc>        floating, the newest build for that openITCOCKPIT release
//   latest        floating, the newest build overall
//
// Tests run for every branch and pull request. Publishing is restricted to
// main, so the floating tags only ever move through a merge.
pipeline {
    environment {
        dockerImage = 'openitcockpit/mcp-server'
      }
    agent any
    stages {
        // Nothing gets published that does not pass the suite first.
        // Runs in the same base image the Dockerfile uses, so the node needs
        // only Docker and the Python version is defined in one place.
        stage('Test') {
            agent {
                label 'rhel8-amd64'
            }
            steps {
                sh script: '''
                    PYTHON_IMAGE=$(awk '/^FROM /{print $2; exit}' Dockerfile)
                    docker run --rm -v "$PWD":/src -w /src "$PYTHON_IMAGE" sh -c '
                        pip install --quiet --upgrade pip
                        pip install --quiet -e ".[dev]"
                        ruff check src tests
                        mypy
                        pytest -q --cov=openitcockpit_mcp
                    '
                '''
            }
        }

        stage('Build and Publish') {
            when {
                branch 'main'
            }
            environment {
                OPENITCOCKPIT_VERSION = sh(
                    returnStdout: true,
                    script: 'cat VERSION'
                ).trim()
                MCP_VERSION = sh(
                    returnStdout: true,
                    script: 'cat MCP_VERSION'
                ).trim()
                RELEASE_TAG = sh(
                    returnStdout: true,
                    script: 'echo "$(cat VERSION)-$(cat MCP_VERSION)"'
                ).trim()
            }
            parallel {
                stage('arm64') {
                    agent {
                        label 'linux-arm64'
                    }
                    steps {
                        sh script: "docker build -f Dockerfile --tag ${dockerImage}:${RELEASE_TAG}-arm64 ."
                        sh script: "docker push ${dockerImage}:${RELEASE_TAG}-arm64"
                    }
                }
                stage('amd64') {
                    agent {
                        label 'rhel8-amd64'
                    }
                    steps {
                        sh script: "docker build -f Dockerfile --tag ${dockerImage}:${RELEASE_TAG}-amd64 ."
                        sh script: "docker push ${dockerImage}:${RELEASE_TAG}-amd64"
                    }
                }
            }
        }

        stage('Merge architectures') {
            when {
                branch 'main'
            }
            agent {
                label 'rhel8-amd64'
            }
            environment {
                OPENITCOCKPIT_VERSION = sh(
                    returnStdout: true,
                    script: 'cat VERSION'
                ).trim()
                RELEASE_TAG = sh(
                    returnStdout: true,
                    script: 'echo "$(cat VERSION)-$(cat MCP_VERSION)"'
                ).trim()
            }
            steps {
                sh "docker buildx imagetools create -t ${dockerImage}:${RELEASE_TAG} -t ${dockerImage}:${OPENITCOCKPIT_VERSION} -t ${dockerImage}:latest ${dockerImage}:${RELEASE_TAG}-amd64 ${dockerImage}:${RELEASE_TAG}-arm64"
            }
         }
    }
}
