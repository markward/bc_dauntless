// native/tests/nif/canonical_dump.cc
#include "canonical_dump.h"

#include <iomanip>

namespace nif::test {

namespace {
void emit_indent(std::ostream& out, int n) {
    for (int i = 0; i < n; ++i) out << "  ";
}
}

void dump_canonical(const File& f, std::ostream& out) {
    out << "file\n";
    emit_indent(out, 1);
    out << "version: 0x" << std::hex << std::setw(8) << std::setfill('0')
        << f.version.value << std::dec << std::setfill(' ') << "\n";
    emit_indent(out, 1);
    out << "num_header_lines: " << f.header_lines.size() << "\n";
    emit_indent(out, 1);
    out << "num_blocks: " << f.blocks.size() << "\n";
    // Block bodies emitted starting in Task 21 (NiNode) and onwards.
}

}  // namespace nif::test
