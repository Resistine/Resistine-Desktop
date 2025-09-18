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

// Helper function to find wg-quick path
func findWgQuickPath() -> String? {
    let wgQuickPaths = [
        "/opt/homebrew/bin/wg-quick",
        "/usr/local/bin/wg-quick",
        "/usr/bin/wg-quick"
    ]
    
    for path in wgQuickPaths {
        if FileManager.default.fileExists(atPath: path) {
            return path
        }
    }
    
    return nil
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
        let process = Process()
        
        // Extract interface name from path (e.g., wg0.conf -> wg0)
        let interfaceName = URL(fileURLWithPath: configPath).deletingPathExtension().lastPathComponent
        
        // Find wg-quick path
        guard let wgQuickPath = findWgQuickPath() else {
            reply("Error: wg-quick not found. Please install WireGuard.")
            return
        }
        
        // Call wg-quick directly
        process.executableURL = URL(fileURLWithPath: wgQuickPath)
        process.arguments = ["up", interfaceName]
        
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
        
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        reply(output.isEmpty ? "VPN started successfully" : output)
    }

    func stopVPN(configPath: String, withReply reply: @escaping (String) -> Void) {
        let process = Process()
        
        // Extract interface name from path
        let interfaceName = URL(fileURLWithPath: configPath).deletingPathExtension().lastPathComponent
        
        // Find wg-quick path
        guard let wgQuickPath = findWgQuickPath() else {
            reply("Error: wg-quick not found. Please install WireGuard.")
            return
        }
        
        // Call wg-quick directly
        process.executableURL = URL(fileURLWithPath: wgQuickPath)
        process.arguments = ["down", interfaceName]
        
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
        
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        reply(output.isEmpty ? "VPN stopped successfully" : output)
    }
    func checkVPNStatus(interfaceName: String, testIP: String?, withReply reply: @escaping (String) -> Void) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        
        // Find wg path (wg command, not wg-quick) for status checking
        let wgPaths = [
            "/opt/homebrew/bin/wg",
            "/usr/local/bin/wg",
            "/usr/bin/wg"
        ]
        
        var wgPath: String?
        for path in wgPaths {
            if FileManager.default.fileExists(atPath: path) {
                wgPath = path
                break
            }
        }
        
        guard let wgCommandPath = wgPath else {
            reply("Error: wg command not found. Please install WireGuard.")
            return
        }

        // Check if WireGuard interface exists and is active
        process.arguments = ["-c", "\(wgCommandPath) show \(interfaceName)"]
        
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
            pingProcess.executableURL = URL(fileURLWithPath: "/bin/bash")
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
            return try CodesignCheck.codeSigningMatches(pid: connection.processIdentifier)
        } catch {
            print("Helper code signing check failed with error: \(error)")
            return false
        }
    }
}

if CommandLine.arguments.count > 1 {
    let command = CommandLine.arguments[1]
    let delegate = HelperToolDelegate() // Create delegate instance
    
    // Handle specific VPN commands
    if command.hasPrefix("startVPN ") {
        let configPath = String(command.dropFirst(9)) // Remove "startVPN "
        delegate.startVPN(configPath: configPath) { result in
            print(result)
            exit(0)
        }
    } else if command.hasPrefix("stopVPN ") {
        let configPath = String(command.dropFirst(8)) // Remove "stopVPN "
        delegate.stopVPN(configPath: configPath) { result in
            print(result)
            exit(0)
        }
    } else if command.hasPrefix("checkVPNStatus ") {
        let tunnelName = String(command.dropFirst(15)) // Remove "checkVPNStatus "
        delegate.checkVPNStatus(interfaceName: tunnelName, testIP: nil, withReply: { result in
            print(result)
            exit(0)
        })
    } else if command.hasPrefix("checkStatusWithIP ") {
        // Handle "checkStatusWithIP /path/to/config.conf 10.49.64.53"
        let parts = command.components(separatedBy: " ")
        if parts.count >= 3 {
            let configPath = parts[1]
            let testIP = parts[2]
            let tunnelName = URL(fileURLWithPath: configPath).deletingPathExtension().lastPathComponent
            delegate.checkVPNStatus(interfaceName: tunnelName, testIP: testIP, withReply: { result in
                print(result)
                exit(0)
            })
        } else {
            print("Error: checkStatusWithIP requires config path and test IP")
            exit(1)
        }
    } else {
        // Handle regular commands
        delegate.runCommand(command: command) { result in
            print(result)
            exit(0)
        }
    }
} else {
    // Normal XPC service mode
    let delegate = HelperToolDelegate()
    let listener = NSXPCListener(machServiceName: "com.resistine.helper")
    listener.delegate = delegate
    listener.resume()
    RunLoop.main.run()
} 