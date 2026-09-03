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
// This is a classic pipeline job wired to main, so there is no branch condition
// to make - BRANCH_NAME only exists in multibranch jobs. Every run tests and
// builds; pushing to the registry is gated on the PUBLISH parameter.
pipeline {
    agent any

    parameters {
        booleanParam(
            name: 'PUBLISH',
            defaultValue: false,
            description: 'Push the built images to the registry. Leave off for a dry run.'
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

        // The pinnable tag must never move. Fail before building rather than
        // silently replacing it at push time.
        stage('Check tag is free') {
            when {
                beforeAgent true
                expression { params.PUBLISH == true }
            }
            agent {
                label 'rhel8-amd64'
            }
            steps {
                sh '''
                    if out=$(docker buildx imagetools inspect "$dockerImage:$RELEASE_TAG" 2>&1); then
                        echo "$dockerImage:$RELEASE_TAG is already published - bump VERSION or MCP_VERSION"
                        exit 1
                    fi
            
                    # Only a genuine "not there" means the tag is free. Anything else - no
                    # network, expired credentials - must not be read as permission to push.
                    case "$out" in
                        *"not found"*|*"manifest unknown"*|*MANIFEST_UNKNOWN*) ;;
                        *)
                            echo "Registry check failed for an unexpected reason:"
                            echo "$out"
                            exit 1
                            ;;
                    esac
                '''
            }
        }

        // Build and push stay on the same agent per architecture: the image
        // only exists in that node's local Docker, so a separate push stage
        // could end up on a different node and find nothing.
        stage('Build and Publish') {
            parallel {
                stage('arm64') {
                    agent {
                        label 'linux-arm64'
                    }
                    stages {
                        stage('build') {
                            steps {
                                sh script: "docker build -f Dockerfile --tag ${dockerImage}:${RELEASE_TAG}-arm64 ."
                            }
                        }
                        stage('push') {
                            when {
                                expression { params.PUBLISH == true }
                            }
                            steps {
                                sh script: "docker push ${dockerImage}:${RELEASE_TAG}-arm64"
                            }
                        }
                    }
                }
                stage('amd64') {
                    agent {
                        label 'rhel8-amd64'
                    }
                    stages {
                        stage('build') {
                            steps {
                                sh script: "docker build -f Dockerfile --tag ${dockerImage}:${RELEASE_TAG}-amd64 ."
                            }
                        }
                        stage('push') {
                            when {
                                expression { params.PUBLISH == true }
                            }
                            steps {
                                sh script: "docker push ${dockerImage}:${RELEASE_TAG}-amd64"
                            }
                        }
                    }
                }
            }
        }

        // Also writes to the registry: it reads both arch images from there and
        // creates the manifest index, moving the floating tags.
        stage('Merge architectures') {
            when {
                beforeAgent true
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
