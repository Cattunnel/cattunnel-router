# Strict JSON reader for exchange replies, without jq/python dependencies.
# Emit only the root subscription and string elements of the root mirrors array.
function ws() { while (substr(src, p, 1) ~ /[ \t\r\n]/ && p <= length(src)) p++ }
function bad() { invalid = 1; exit 1 }
function string(    out,c,e,h,n,i) {
    if (substr(src,p++,1) != "\"") bad()
    out = ""
    while (p <= length(src)) {
        c = substr(src,p++,1)
        if (c == "\"") return out
        if (c ~ /[[:cntrl:]]/) bad()
        if (c == "\\") {
            e = substr(src,p++,1)
            if (e == "\"" || e == "\\" || e == "/") c = e
            else if (e == "n") c = "\n"
            else if (e == "r") c = "\r"
            else if (e == "t") c = "\t"
            else if (e == "b") c = sprintf("%c",8)
            else if (e == "f") c = sprintf("%c",12)
            else if (e == "u") {
                h = tolower(substr(src,p,4)); p += 4
                if (length(h) != 4 || h ~ /[^0-9a-f]/) bad()
                n = 0
                for (i=1;i<=4;i++) n = n*16 + index("0123456789abcdef",substr(h,i,1))-1
                # URLs use ASCII escapes. Other metadata is ignored without decoding.
                c = (n >= 32 && n <= 126) ? sprintf("%c",n) : "?"
            } else bad()
        }
        out = out c
    }
    bad()
}
function value(depth, target,    c,key,v,start) {
    if (depth > 16) bad()
    ws(); c = substr(src,p,1)
    if (c == "\"") {
        v = string()
        if (target == "subscription") suburl = v
        if (target == "mirror") mirrors[++count] = v
    } else if (c == "{") {
        p++; ws()
        if (substr(src,p,1) == "}") { p++; return }
        while (1) {
            ws(); key = string(); ws()
            if (substr(src,p++,1) != ":") bad()
            value(depth+1, depth == 0 ? key : "")
            ws(); c = substr(src,p++,1)
            if (c == "}") break
            if (c != ",") bad()
        }
    } else if (c == "[") {
        p++; ws()
        if (substr(src,p,1) == "]") { p++; return }
        while (1) {
            ws()
            if (target == "mirrors" && substr(src,p,1) != "\"") bad()
            value(depth+1, target == "mirrors" ? "mirror" : "")
            ws(); c = substr(src,p++,1)
            if (c == "]") break
            if (c != ",") bad()
        }
    } else {
        start = p
        while (p <= length(src) && substr(src,p,1) !~ /[ \t\r\n,}\]]/) p++
        v = substr(src,start,p-start)
        if (v !~ /^(true|false|null|-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?)$/) bad()
        if (target == "subscription") bad()
    }
}
{ src = src $0 "\n"; if (length(src) > 65536) bad() }
END {
    if (invalid) exit 1
    p = 1; ws()
    if (substr(src,p,1) != "{") bad()
    value(0, ""); ws()
    if (p <= length(src)) bad()
    if (count) { for (i=1;i<=count;i++) print mirrors[i] }
    else if (suburl != "") print suburl
    else exit 1
}
