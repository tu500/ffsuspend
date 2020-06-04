set -e
rm -rf build dist ffsuspend.egg-info
python3 setup.py sdist
python3 setup.py bdist_wheel
echo Packaging successful
