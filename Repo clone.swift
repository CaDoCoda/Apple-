import Foundation

// MARK: - Shell Runner

@discardableResult
func run(_ command: String, log: FileHandle?) -> Int32 {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/bin/bash")
    process.arguments = ["-c", command]

    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = pipe

    do {
        try process.run()
    } catch {
        let msg = "Failed to run command: \(command)\n"
        print(msg)
        log?.write(msg.data(using: .utf8)!)
        return -1
    }

    process.waitUntilExit()

    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    if let output = String(data: data, encoding: .utf8) {
        print(output)
        log?.write(output.data(using: .utf8)!)
    }

    return process.terminationStatus
}

// MARK: - Setup

let repos = [
    "https://github.com/Stichting-MINIX-Research-Foundation/minix.git",
    "https://github.com/Stichting-MINIX-Research-Foundation/netbsd.git",
    "https://github.com/Stichting-MINIX-Research-Foundation/xsrc.git",
    "https://github.com/Stichting-MINIX-Research-Foundation/u-boot.git",
    "https://github.com/Stichting-MINIX-Research-Foundation/pkgsrc-ng.git",
    "https://github.com/Stichting-MINIX-Research-Foundation/gsoc.git"
]

// Create workspace
let workspace = "minix_workspace"
run("mkdir -p \(workspace)", log: nil)

// Create log file
let formatter = DateFormatter()
formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss"
let timestamp = formatter.string(from: Date())
let logPath = "\(workspace)/clone_log_\(timestamp).txt"
FileManager.default.createFile(atPath: logPath, contents: nil)
let logHandle = FileHandle(forWritingAtPath: logPath)

// MARK: - Clone + Fetch + Checkout Branches

func cloneRepo(_ repo: String) {
    let name = repo.split(separator: "/").last!.replacingOccurrences(of: ".git", with: "")
    let dir = "\(workspace)/\(name)"

    let header = "\n=== Processing \(name) ===\n"
    print(header)
    logHandle?.write(header.data(using: .utf8)!)

    // Retry clone up to 3 times
    var success = false
    for attempt in 1...3 {
        let msg = "Cloning attempt \(attempt) for \(name)...\n"
        print(msg)
        logHandle?.write(msg.data(using: .utf8)!)

        let status = run("cd \(workspace) && git clone \(repo)", log: logHandle)
        if status == 0 {
            success = true
            break
        }
    }

    if !success {
        let fail = "Failed to clone \(name) after 3 attempts.\n"
        print(fail)
        logHandle?.write(fail.data(using: .utf8)!)
        return
    }

    // Fetch all branches
    run("cd \(dir) && git fetch --all --prune --tags", log: logHandle)

    // Checkout every remote branch locally
    let branchesOutput = run("cd \(dir) && git branch -r", log: logHandle)
    if branchesOutput == 0 {
        let list = try? String(contentsOfFile: logPath)
        let lines = list?.components(separatedBy: "\n") ?? []

        for line in lines {
            if line.contains("origin/") && !line.contains("HEAD") {
                let branch = line.trimmingCharacters(in: .whitespaces)
                let local = branch.replacingOccurrences(of: "origin/", with: "")
                run("cd \(dir) && git checkout -B \(local) \(branch)", log: logHandle)
            }
        }
    }

    let done = "Finished \(name).\n"
    print(done)
    logHandle?.write(done.data(using: .utf8)!)
}

// MARK: - Parallel Execution

let queue = DispatchQueue(label: "cloneQueue", attributes: .concurrent)
let group = DispatchGroup()

for repo in repos {
    group.enter()
    queue.async {
        cloneRepo(repo)
        group.leave()
    }
}

group.wait()

let final = "\nAll repositories processed. Log saved to \(logPath)\n"
print(final)
logHandle?.write(final.data(using: .utf8)!)
logHandle?.closeFile()
