from setuptools import setup, find_packages

setup(
        name="spaceboi",
        version="0.1.3",
        author="ericpar234",
        description="A radio satellite event tracker.",
        long_description=open("README.md").read(),
        long_description_content_type="text/markdown",
        url="https://github.com/ericpar234/spaceboi",
        packages=find_packages(),
        py_modules=["spaceboi"],
        install_requires=open("requirements.txt").read().splitlines(),
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: OS Independent",
        ],
        python_requires=">=3.10",

        entry_points={
            "console_scripts": [
                "spaceboi = spaceboi:main"
            ]
        },
)
