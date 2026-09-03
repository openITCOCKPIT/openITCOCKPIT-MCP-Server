// Image tags are <openITCOCKPIT version>-<MCP server version>, e.g. 5.7.1-2.0.0.
// VERSION holds the openITCOCKPIT release this build targets; MCP_VERSION holds
// this server's own semantic version, so a fix can ship without openITCOCKPIT
// moving and a pinned tag never changes behaviour underneath a user.
//
// Published per build:
//   <oitc>-<mcp>  immutable, the one to pin
//   <oitc>        floating, the newest build for that openITCOCKPIT release
//   latest        floating, the newest build overall
//
// Tests run on every branch. Publishing needs main *and* the PUBLISH parameter,
// so a build can be triggered for its test results without touching the
// registry.
pipeline {
    agent any

    parameters {
        booleanParam(
            name: 'PUBLISH',
            defaultValue: false,
            description: 'Build and push images to the registry. Leave off for a test-only run.'
        )
    }

    environment {
        dockerImage           = 'openitcockpit/mcp-server'
        OPENITCOCKPIT_VERSION = sh(returnStdout: true, script: 'cat VERSION').trim()
        MCP_VERSION           = sh(returnStdout: true, script: 'cat MCP_VERSION').trim()
        RELEASE_TAG           = "${OPENITCOCKPIT_VERSION}-${MCP_VERSION}"
    }

    stages {
        // Nothing gets published that does not pass the suite first.
        // The script runs the checks inside the image the Dockerfile is based
        // on, so the node needs only Docker and developers can run the exact
        // same thing locally.
        stage('Test') {
            agent {
                label 'rhel8-amd64'
            }
            steps {
                sh './scripts/checks-docker.sh'
            }
        }

        stage('Build and Publish') {
            when {
                branch 'main'
                expression { params.PUBLISH }
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

        // Also writes to the registry: it reads both arch images from there and
        // creates the manifest index, moving the floating tags.
        stage('Merge architectures') {
            when {
                beforeAgent true
                branch 'main'
                expression { params.PUBLISH == true }
            }
            agent {
                label 'rhel8-amd64'
            }
            steps {
                sh "docker buildx imagetools create -t ${dockerImage}:${RELEASE_TAG} -t ${dockerImage}:${OPENITCOCKPIT_VERSION} -t ${dockerImage}:latest ${dockerImage}:${RELEASE_TAG}-amd64 ${dockerImage}:${RELEASE_TAG}-arm64"
            }
        }
    }
}
