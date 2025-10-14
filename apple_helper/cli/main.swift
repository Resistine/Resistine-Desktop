import Foundation
import ServiceManagement

@objc(HelperToolProtocol)
public protocol HelperToolProtocol {
    func runCommand(command: String, withReply reply: @escaping (String) -> Void)
    func startVPN(configPath: String, withReply reply: @escaping (String) -> Void)
    func stopVPN(configPath: String, withReply reply: @escaping (String) -> Void)
    func checkVPNStatus(interfaceName: String, testIP: String?, withReply reply: @escaping (String) -> Void)
}

enum Command: String {
    case startVPN = "start-vpn"
    case stopVPN = "stop-vpn"
    case status = "status"
    case run = "run"
    case registerDaemon = "register-daemon"
    case authStatus = "auth-status"
    case openLoginItems = "open-login-items"
    case help = "help"
}

func usage(_ code: Int32 = 2) -> Never {
    let text = """
    Usage:
      ResistCli start-vpn <configPath>
      ResistCli stop-vpn <configPath>
      ResistCli status <interfaceName> [testIP]
      ResistCli run <shell command>
      ResistCli register-daemon
      ResistCli auth-status
      ResistCli open-login-items

    Talks to com.resistine.helper via privileged XPC and prints the reply.
    ServiceManagement commands for daemon registration and status.
    """
    FileHandle.standardError.write(Data(text.utf8))
    exit(code)
}

let args = CommandLine.arguments.dropFirst()
guard let sub = args.first, let cmd = Command(rawValue: sub) else { usage() }

// Keep a strong reference to the XPC connection for the lifetime of the process
var xpcConnection: NSXPCConnection?

func connect() -> HelperToolProtocol? {
    if xpcConnection == nil {
        let connection = NSXPCConnection(machServiceName: "com.resistine.helper", options: .privileged)
        connection.remoteObjectInterface = NSXPCInterface(with: HelperToolProtocol.self)
        connection.resume()
        xpcConnection = connection
    }
    var proxy: HelperToolProtocol?
    proxy = xpcConnection?.remoteObjectProxyWithErrorHandler { err in
        let msg = "XPC connection error: \(err.localizedDescription)\n"
        FileHandle.standardError.write(Data(msg.utf8))
        exit(3)
    } as? HelperToolProtocol
    return proxy
}

func requireProxy() -> HelperToolProtocol {
    guard let p = connect() else {
        FileHandle.standardError.write(Data("Failed to create XPC proxy\n".utf8))
        exit(3)
    }
    return p
}

func waitReply(_ fn: (@escaping (String) -> Void) -> Void) -> String {
    let sem = DispatchSemaphore(value: 0)
    var result = ""
    fn { reply in
        result = reply
        sem.signal()
    }
    let waited = sem.wait(timeout: .now() + 60)
    if waited == .timedOut {
        return ""
    }
    return result
}

// Locate the LaunchDaemon plist inside the surrounding .app bundle
func resolveDaemonPlistPath() -> String? {
    let bundlePath = Bundle.main.bundlePath // e.g. .../Contents/Library/LaunchServices
    let bundleURL = URL(fileURLWithPath: bundlePath)
    // Go up twice: LaunchServices -> Library -> Contents
    let contentsURL = bundleURL.deletingLastPathComponent().deletingLastPathComponent()
    let plistURL = contentsURL.appendingPathComponent("Library/LaunchDaemons/com.resistine.plist")
    let path = plistURL.path
    return FileManager.default.fileExists(atPath: path) ? path : nil
}

switch cmd {
case .registerDaemon:
    do {
        print("🔍 Searching for plist file...")
        print("📦 CLI bundle path: \(Bundle.main.bundlePath)")
        guard let plistPath = resolveDaemonPlistPath() else {
            print("❌ Plist not found in app bundle (expected at Contents/Library/LaunchDaemons/com.resistine.plist)")
            exit(1)
        }
        print("✅ Found plist in app bundle: \(plistPath)")
        print("🔧 Creating SMAppService with plist name: com.resistine.plist")
        // IMPORTANT: Pass the plist NAME, not full path
        let service = SMAppService.daemon(plistName: "com.resistine.plist")
        
        print("📊 Current status before registration: \(service.status)")
        print("🚀 Attempting to register daemon...")
        
        try service.register()
        
        print("📊 Status after registration: \(service.status)")
        
        switch service.status {
        case .enabled: 
            print("✅ enabled")
            exit(0)
        case .requiresApproval: 
            print("⚠️ requiresApproval")
            exit(0)
        case .notRegistered: 
            print("❌ notRegistered")
            exit(1)
        case .notFound: 
            print("❌ notFound")
            exit(1)
        @unknown default: 
            print("❓ unknown")
            exit(1)
        }
    } catch {
        print("❌ Registration failed with error: \(error.localizedDescription)")
        FileHandle.standardError.write(Data("register failed: \(error.localizedDescription)\n".utf8))
        exit(1)
    }

case .authStatus:
    print("🔍 Checking daemon status...")
    print("📦 CLI bundle path: \(Bundle.main.bundlePath)")
    guard let plistPath = resolveDaemonPlistPath() else {
        print("❌ Plist not found in app bundle (expected at Contents/Library/LaunchDaemons/com.resistine.plist)")
        exit(1)
    }
    print("✅ Found plist in app bundle: \(plistPath)")
    print("🔧 Creating SMAppService with plist name: com.resistine.plist")
    // IMPORTANT: Pass the plist NAME, not full path
    let service = SMAppService.daemon(plistName: "com.resistine.plist")
    
    print("📊 Current daemon status: \(service.status)")
    
    switch service.status {
    case .enabled: 
        print("✅ enabled")
        exit(0)
    case .requiresApproval: 
        print("⚠️ requiresApproval")
        exit(2)
    case .notRegistered: 
        print("❌ notRegistered")
        exit(3)
    case .notFound: 
        print("❌ notFound")
        exit(4)
    @unknown default: 
        print("❓ unknown")
        exit(5)
    }

case .openLoginItems:
    SMAppService.openSystemSettingsLoginItems()
    print("opened")
    exit(0)
case .startVPN:
    let proxy = requireProxy()
    guard args.count >= 2 else { usage() }
    let config = String(args.dropFirst().first!)
    let reply = waitReply { proxy.startVPN(configPath: config, withReply: $0) }
    print(reply)
    if reply.isEmpty || reply.lowercased().contains("error") {
        exit(1)
    } else {
        exit(0)
    }

case .stopVPN:
    let proxy = requireProxy()
    guard args.count >= 2 else { usage() }
    let config = String(args.dropFirst().first!)
    let reply = waitReply { proxy.stopVPN(configPath: config, withReply: $0) }
    print(reply)
    if reply.isEmpty || reply.lowercased().contains("error") {
        exit(1)
    } else {
        exit(0)
    }

case .status:
    let proxy = requireProxy()
    guard args.count >= 2 else { usage() }
    let parts = Array(args.dropFirst())
    let iface = parts[0]
    let testIP = parts.count > 1 ? parts[1] : nil
    let reply = waitReply { proxy.checkVPNStatus(interfaceName: iface, testIP: testIP, withReply: $0) }
    print(reply)
    exit(reply.isEmpty ? 1 : 0)

case .run:
    let proxy = requireProxy()
    guard args.count >= 2 else { usage() }
    let command = Array(args.dropFirst()).joined(separator: " ")
    let reply = waitReply { proxy.runCommand(command: command, withReply: $0) }
    print(reply)
    exit(0)

case .help:
    usage(0)
}


