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
    let possiblePaths = [
        "/opt/homebrew/bin/bash",  // Apple Silicon Homebrew
        "/usr/local/bin/bash",     // Intel Homebrew
        "/bin/bash"                // System bash (fallback)
    ]
    
    for path in possiblePaths {
        if FileManager.default.fileExists(atPath: path) {
            // Check bash version for bundled WireGuard compatibility
            let process = Process()
            process.executableURL = URL(fileURLWithPath: path)
            process.arguments = ["--version"]
            
            let pipe = Pipe()
            process.standardOutput = pipe
            
            do {
                try process.run()
                process.waitUntilExit()
                
                let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                
                // Check if it's bash 4+ (wg-quick requirement)
                if output.contains("GNU bash, version 4") || output.contains("GNU bash, version 5") {
                    return path
                }
            } catch {
                continue
            }
        }
    }
    
    return nil

}
func findWgQuick() -> String? {
    // Use only system WireGuard installations
    let systemPaths = [
        "/usr/bin/wg-quick",          // System installation (macOS built-in)
        "/opt/homebrew/bin/wg-quick", // Apple Silicon Homebrew
        "/usr/local/bin/wg-quick"     // Intel Homebrew
    ]
    
    for path in systemPaths {
        if FileManager.default.fileExists(atPath: path) {
            print("✅ [TOOLS] Found system wg-quick at: \(path)")
            return path
        }
    }
    
    print("❌ [TOOLS] No system wg-quick found. Please install WireGuard via Homebrew or system package manager.")
    return nil
}

func findSystemBash() -> String? {
    // Look for bash 4+ in system locations
    let bashPaths = [
        "/opt/homebrew/bin/bash",  // Apple Silicon Homebrew bash 5
        "/usr/local/bin/bash",     // Intel Homebrew bash 5
        "/bin/bash"                // System bash (fallback)
    ]
    
    for path in bashPaths {
        if FileManager.default.fileExists(atPath: path) {
            print("✅ [TOOLS] Found bash at: \(path)")
            return path
        }
    }
    
    print("❌ [TOOLS] No bash found in system locations")
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
        print("🔧 [VPN] Starting VPN with config: \(configPath)")
        
        guard FileManager.default.fileExists(atPath: configPath) else {
            let error = "Error: Config file not found at \(configPath)"
            print("❌ [VPN] \(error)")
            reply(error)
            return
        }
        
        guard let bashPath = findSystemBash() else {
            let error = "Error: bash (4+) not found. Please install bash 4+ via Homebrew."
            print("❌ [VPN] \(error)")
            reply(error)
            return
        }
        print("✅ [VPN] Found bash at: \(bashPath)")
        
        guard let wgQuickPath = findWgQuick() else {
            let error = "Error: wg-quick not found. Please install WireGuard."
            print("❌ [VPN] \(error)")
            reply(error)
            return
        }
        print("✅ [VPN] Found wg-quick at: \(wgQuickPath)")
        
        // Fix file permissions if world-accessible (to avoid the warning)
        let chmodProcess = Process()
        chmodProcess.executableURL = URL(fileURLWithPath: "/bin/chmod")
        chmodProcess.arguments = ["600", configPath]
        try? chmodProcess.run()
        chmodProcess.waitUntilExit()
        
        let process = Process()
        process.executableURL = URL(fileURLWithPath: bashPath)
        process.environment = [
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        ]
        
        // Use the FULL path to the config file - wg-quick accepts this!
        process.arguments = ["-c", "\(wgQuickPath) up '\(configPath)'"]
        
        print("🚀 [VPN] Executing: \(bashPath) -c '\(wgQuickPath) up \(configPath)'")
        
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        
        do {
            try process.run()
            process.waitUntilExit()
            print("📊 [VPN] Process exit code: \(process.terminationStatus)")
        } catch {
            let errorMsg = "Failed to start VPN: \(error.localizedDescription)"
            print("❌ [VPN] \(errorMsg)")
            reply(errorMsg)
            return
        }
        
        let output = String(
            data: pipe.fileHandleForReading.readDataToEndOfFile(),
            encoding: .utf8
        )?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        
        print("📤 [VPN] Output: \(output)")
        
        if process.terminationStatus == 0 {
            reply("VPN started successfully")
        } else {
            reply("Error starting VPN: \(output)")
        }
    }

func stopVPN(configPath: String, withReply reply: @escaping (String) -> Void) {
    print("🛑 [VPN] Stopping VPN with config: \(configPath)")
    
    guard let bashPath = findSystemBash() else {
        let error = "Error: bash (4+) not found. Please install bash 4+ via Homebrew."
        print("❌ [VPN] \(error)")
        reply(error)
        return
    }
    print("✅ [VPN] Found bash at: \(bashPath)")
    
    guard let wgQuickPath = findWgQuick() else {
        let error = "Error: wg-quick not found. Please install WireGuard."
        print("❌ [VPN] \(error)")
        reply(error)
        return
    }
    print("✅ [VPN] Found wg-quick at: \(wgQuickPath)")
    
    let process = Process()
    process.executableURL = URL(fileURLWithPath: bashPath)
    process.environment = [
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    ]
    
    // Use the FULL path to the config file
    process.arguments = ["-c", "\(wgQuickPath) down '\(configPath)'"]
    
    print("🚀 [VPN] Executing: \(bashPath) -c '\(wgQuickPath) down \(configPath)'")
    
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = pipe
    
    do {
        try process.run()
        process.waitUntilExit()
        print("📊 [VPN] Process exit code: \(process.terminationStatus)")
    } catch {
        let errorMsg = "Failed to stop VPN: \(error.localizedDescription)"
        print("❌ [VPN] \(errorMsg)")
        reply(errorMsg)
        return
    }
    
    let output = String(
        data: pipe.fileHandleForReading.readDataToEndOfFile(),
        encoding: .utf8
    )?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    
    print("📤 [VPN] Output: \(output)")
    reply(output.isEmpty ? "VPN stopped successfully" : output)
}
    func checkVPNStatus(interfaceName: String, testIP: String?, withReply reply: @escaping (String) -> Void) {
        print("🔍 [VPN] Checking status for interface: \(interfaceName)")
        
        guard let bashPath = findSystemBash() else {
            print("❌ [VPN] bash not found, returning Stopped")
            reply("Stopped")
            return
        }
        
        
        let ifconfigProcess = Process()
        ifconfigProcess.executableURL = URL(fileURLWithPath: bashPath)
        ifconfigProcess.environment = [
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        ]
        ifconfigProcess.arguments = ["-c", "ifconfig \(interfaceName) 2>/dev/null"]
        
        print("🚀 [VPN] Checking interface with ifconfig")
        
        let ifconfigPipe = Pipe()
        ifconfigProcess.standardOutput = ifconfigPipe
        ifconfigProcess.standardError = ifconfigPipe
        
        do {
            try ifconfigProcess.run()
            ifconfigProcess.waitUntilExit()
        } catch {
            print("❌ [VPN] ifconfig error: \(error.localizedDescription)")
            reply("Stopped")
            return
        }
        
        let ifconfigOutput = String(
            data: ifconfigPipe.fileHandleForReading.readDataToEndOfFile(),
            encoding: .utf8
        )?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        
        // Check if interface exists and is UP
        let interfaceExists = !ifconfigOutput.isEmpty &&
            ifconfigOutput.contains("flags=") &&
            ifconfigOutput.contains("UP") &&
            ifconfigProcess.terminationStatus == 0
        
        if !interfaceExists {
            print("📊 [VPN] Interface not found or DOWN, returning Stopped")
            reply("Stopped")
            return
        }
        
        print("✅ [VPN] Interface \(interfaceName) is UP")
        
        // ✅ Step 2: Optional connectivity test (only if testIP provided and valid)
        if let testIP = testIP, !testIP.isEmpty, testIP != "0.0.0.0" {
            print("🌐 [VPN] Testing connectivity to: \(testIP)")
            
            let pingProcess = Process()
            pingProcess.executableURL = URL(fileURLWithPath: bashPath)
            pingProcess.environment = [
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            ]
            
            // Use shorter timeout: -W 1000 = 1 second, -c 1 = 1 packet
            pingProcess.arguments = [
                "-c",
                "ping -c 1 -W 1000 \(testIP) > /dev/null 2>&1 && echo 'SUCCESS' || echo 'FAILED'"
            ]
            
            let pingPipe = Pipe()
            pingProcess.standardOutput = pingPipe
            pingProcess.standardError = pingPipe
            
            do {
                try pingProcess.run()
                pingProcess.waitUntilExit()
                
                let pingOutput = String(
                    data: pingPipe.fileHandleForReading.readDataToEndOfFile(),
                    encoding: .utf8
                )?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                
                if pingOutput.contains("SUCCESS") {
                    print("✅ [VPN] Connectivity test passed, returning Running")
                    reply("Running")
                } else {
                    print("⚠️ [VPN] Connectivity test failed, but interface is UP - returning Running anyway")
                    // Interface is UP, so consider it running even if ping fails
                    reply("Running")
                }
            } catch {
                print("⚠️ [VPN] Ping error but interface exists: \(error.localizedDescription)")
                // If ping fails but interface exists, still consider it running
                reply("Running")
            }
        } else {
            // No test IP provided, interface is UP, so it's running
            print("📊 [VPN] No connectivity test, interface is UP, returning Running")
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
