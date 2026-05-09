// native/tests/nif/canonical_dump.h
#pragma once

#include <nif/file.h>

#include <ostream>

namespace nif::test {

void dump_canonical(const File& f, std::ostream& out);

}  // namespace nif::test
