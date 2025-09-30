//
//  main.swift
//  HelperTool
//
//  Created by Alin Lupascu on 2/25/25.
//

import Foundation

@objc(HelperToolProtocol)
public protocol HelperToolProtocol {
    func runCommand(command: String, withReply reply: @escaping (String) -> Void)
    func startVPN(configPath: String, withReply reply: @escaping (String) -> Void)
    func stopVPN(configPath: String, withReply reply: @escaping (String) -> Void)
    func checkVPNStatus(interfaceName: String, testIP: String?, withReply reply: @escaping (String) -> Void)
}
func findHomebrewBash() -> String? {
    let possiblePaths = ["/opt/homebrew/bin/bash", "/usr/local/bin/bash"]
    return possiblePaths.first { FileManager.default.fileExists(atPath: $0) }
}
func findWgQuick() -> String? {
    let possiblePaths = ["/opt/homebrew/bin/wg-quick", "/usr/local/bin/wg-quick", "/usr/bin/wg-quick"]
    return possiblePaths.first { FileManager.default.fileExists(atPath: $0) }
}
// XPC Communication setup
class HelperToolDelegate: NSObject, NSXPCListenerDelegate, HelperToolProtocol {
    // Accept new XPC connections by setting up the exported interface and object.
    func listener(_ listener: NSXPCListener, shouldAcceptNewConnection newConnection: NSXPCConnection) -> Bool {
        // Validate that the main app and helper app have the same code signing identity, otherwise return
        guard isValidClient(connection: newConnection) else {
            print("❌ Rejected connection from unauthorized client")
            return false
        }

        newConnection.exportedInterface = NSXPCInterface(with: HelperToolProtocol.self)
        newConnection.exportedObject = self
        newConnection.resume()
        return true
    }

    // Execute the shell command and reply with output.
    func runCommand(command: String, withReply reply: @escaping (String) -> Void) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-c", command]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            reply("Failed to run command: \(error.localizedDescription)")
            return
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        reply(output.isEmpty ? "No output" : output)
    }

    func startVPN(configPath: String, withReply reply: @escaping (String) -> Void) {
        guard let bashPath = findHomebrewBash() else {
            reply("Error: Homebrew bash (4+) not found. Please install.")
            return
        }
        
        guard let wgQuickPath = findWgQuick() else {
            reply("Error: wg-quick not found. Please install WireGuard.")
            return
        }
        
        let process = Process()
        process.executableURL = URL(fileURLWithPath: bashPath)
        process.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"]
        
        let interfaceName = URL(fileURLWithPath: configPath).deletingPathExtension().lastPathComponent
        process.arguments = ["-c", "\(wgQuickPath) up \(interfaceName)"]
        
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            reply("Failed to start VPN: \(error.localizedDescription)")
            return
        }
        
        let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        
        reply(output.isEmpty ? "VPN started successfully" : output)
    }

    func stopVPN(configPath: String, withReply reply: @escaping (String) -> Void) {
        guard let bashPath = findHomebrewBash() else {
            reply("Error: Homebrew bash (4+) not found. Please install.")
            return
        }
        
        guard let wgQuickPath = findWgQuick() else {
            reply("Error: wg-quick not found. Please install WireGuard.")
            return
        }
        
        let process = Process()
        process.executableURL = URL(fileURLWithPath: bashPath)
        process.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"]
        
        let interfaceName = URL(fileURLWithPath: configPath).deletingPathExtension().lastPathComponent
        process.arguments = ["-c", "\(wgQuickPath) down \(interfaceName)"]
        
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            reply("Failed to stop VPN: \(error.localizedDescription)")
            return
        }
        
        let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        
        reply(output.isEmpty ? "VPN stopped successfully" : output)
    }
    
    func checkVPNStatus(interfaceName: String, testIP: String?, withReply reply: @escaping (String) -> Void) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/opt/homebrew/bin/bash")
        
        // Check if WireGuard interface exists and is active
        let wgCommand = "wg show \(interfaceName)"
        process.arguments = ["-c", wgCommand]
        
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            reply("Stopped")
            return
        }
        
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        
        // If wg show returns empty output or error message, the interface is not active
        if output.isEmpty || output.contains("No such file or directory") || output.contains("Unable to access interface") || output.contains("Permission denied") {
            reply("Stopped")
            return
        }
        
        // If we get here and have output, the interface is active
        if output.contains("interface:") {
            reply("Running")
            return
        }
        
        // If test IP is provided, test connectivity
        if let testIP = testIP, !testIP.isEmpty {
            let pingProcess = Process()
            pingProcess.executableURL = URL(fileURLWithPath: "/opt/homebrew/bin/bash")
            pingProcess.arguments = ["-c", "ping -c 4 \(testIP)"]
            
            let pingPipe = Pipe()
            pingProcess.standardOutput = pingPipe
            pingProcess.standardError = pingPipe
            
            do {
                try pingProcess.run()
                pingProcess.waitUntilExit()
                
                if pingProcess.terminationStatus == 0 {
                    reply("Running")
                } else {
                    reply("Stopped")
                }
            } catch {
                reply("Stopped")
            }
        } else {
            // If no test IP provided, just check if interface exists
            reply("Running")
        }
    }

    
    

    // Check that the codesigning matches between the main app and the helper app
    private func isValidClient(connection: NSXPCConnection) -> Bool {
        do {
            // Prefer TeamIdentifier match to allow different leaf certs from same Team
            if let selfTeam = try CodesignCheck.teamIdentifierForSelf(),
               let peerTeam = try CodesignCheck.teamIdentifier(forPID: connection.processIdentifier) {
                return selfTeam == peerTeam
            }
            // Fallback to strict certificate chain comparison
            return try CodesignCheck.codeSigningMatches(pid: connection.processIdentifier)
        } catch {
            print("Helper code signing check failed with error: \(error)")
            return false
        }
    }
}

// Normal XPC service mode
let delegate = HelperToolDelegate()
let listener = NSXPCListener(machServiceName: "com.resistine.helper")
listener.delegate = delegate
listener.resume()
RunLoop.main.run()


