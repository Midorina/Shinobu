module.exports = {
    apps: [{
        name: "shinobu",
        script: "./run.py",
        interpreter: "./venv/bin/python",
        args: "shinobu"
    },
        {
            name: "shinobu_ipc",
            script: "./ipc/ipc.py",
            interpreter: "./venv/bin/python",
            args: "--port 13337"
        }
    ]
}