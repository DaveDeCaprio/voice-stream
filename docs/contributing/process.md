# Process

## Poetry

Dependencies are managed using [Poetry].  After cloning the repo, run poetry from the root directory:

`poetry install --all-extras`

This will create a virtual environment in the `.venv` directory and install all dependencies there.

`poetry shell` will open a shell in that virtual environment.

## Building docs

Change to the docs directory and run `make html`

Any warnings in the doc build will cause the real doc build to fail.

For more work on docs, run `sphinx-autobuild docs docs/_build/html --port 8001`.  This starts a live updating server for the docs.

## Running integration tests

To run the integration tests you need to set up a /.env file with appropriate credentials.  See /.env.example for details. 



