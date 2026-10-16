// Pasteboard + keyboard helpers for polish.py (JXA). Usage: osascript -l JavaScript clip.js <cmd> [file]
ObjC.import("AppKit");
ObjC.import("Foundation");
function readFile(p) { return ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(p, $.NSUTF8StringEncoding, null)); }
function writeFile(p, s) { $(s).writeToFileAtomicallyEncodingError(p, true, $.NSUTF8StringEncoding, null); }
function run(argv) {
  var pb = $.NSPasteboard.generalPasteboard, cmd = argv[0];
  if (cmd === "count") return String(pb.changeCount);
  if (cmd === "front") return ObjC.unwrap($.NSWorkspace.sharedWorkspace.frontmostApplication.localizedName);
  if (cmd === "mods") return String($.NSEvent.modifierFlags & 0xFFFF0000);
  if (cmd === "read") {  // dump every type as base64 to file
    var out = { count: pb.changeCount, types: {} };
    ObjC.deepUnwrap(pb.types).forEach(function (t) {
      var d = pb.dataForType(t);
      if (d && !d.isNil()) out.types[t] = ObjC.unwrap(d.base64EncodedStringWithOptions(0));
    });
    writeFile(argv[1], JSON.stringify(out));
    return "";
  }
  if (cmd === "write") {  // replace clipboard with {type: base64}
    var types = JSON.parse(readFile(argv[1])).types;
    pb.clearContents;
    Object.keys(types).forEach(function (t) {
      pb.setDataForType($.NSData.alloc.initWithBase64EncodedStringOptions(types[t], 0), t);
    });
    return String(pb.changeCount);
  }
}
