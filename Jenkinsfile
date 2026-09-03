// Image tags are this server's own semantic version and nothing else, e.g.
// 0.1.0, read from MCP_VERSION.
//
// Published per build:
//   0.1.0   immutable, the one to pin
//   latest  floating, the newest release - unless PUBLISH_LATEST is off
//
// Two tags are the whole contract: pin an exact version, or track latest and
// read the changelog. Floating minor and major tags were considered and left
// out - they promise "newer but compatible", which is a promise 0.x cannot
// make, since below 1.0.0 it is the minor that carries breaking changes.
//
// The openITCOCKPIT release this server supports is deliberately not in the
// tag: the openITCOCKPIT API is backwards compatible, so a tag naming one
// release would assert a binding that does not exist. The supported range is
// in the README and in the server's own banner.
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
        booleanParam(
            name: 'PUBLISH_LATEST',
            defaultValue: true,
            description: 'Also move the latest tag onto this build. Only has an effect when PUBLISH is on. Turn it off for a backport or a pre-release that should not become what a bare "docker pull" gets.'
        )
    }

    environment {
        dockerImage = 'openitcockpit/mcp-server'
        MCP_VERSION = sh(returnStdout: true, script: 'cat MCP_VERSION').trim()
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
                    if out=$(docker buildx imagetools inspect "$dockerImage:$MCP_VERSION" 2>&1); then
                        echo "$dockerImage:$MCP_VERSION is already published - bump MCP_VERSION"
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
                                sh script: "docker build -f Dockerfile --tag ${dockerImage}:${MCP_VERSION}-arm64 ."
                            }
                        }
                        stage('push') {
                            when {
                                expression { params.PUBLISH == true }
                            }
                            steps {
                                sh script: "docker push ${dockerImage}:${MCP_VERSION}-arm64"
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
                                sh script: "docker build -f Dockerfile --tag ${dockerImage}:${MCP_VERSION}-amd64 ."
                            }
                        }
                        stage('push') {
                            when {
                                expression { params.PUBLISH == true }
                            }
                            steps {
                                sh script: "docker push ${dockerImage}:${MCP_VERSION}-amd64"
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
                // Jenkins exposes the build parameters as environment
                // variables, so the shell can read PUBLISH_LATEST directly.
                sh '''
                    docker buildx imagetools create \
                        -t "$dockerImage:$MCP_VERSION" \
                        "$dockerImage:${MCP_VERSION}-amd64" \
                        "$dockerImage:${MCP_VERSION}-arm64"

                    # A second create just points latest at the manifest that
                    # now exists - no rebuild, no re-upload.
                    if [ "$PUBLISH_LATEST" = "true" ]; then
                        docker buildx imagetools create \
                            -t "$dockerImage:latest" \
                            "$dockerImage:$MCP_VERSION"
                    else
                        echo "PUBLISH_LATEST is off - leaving the latest tag where it is"
                    fi
                '''
            }
        }
    }
}
