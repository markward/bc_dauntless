// native/src/nif/src/dispatch.h
//
// Block-parser dispatch table. v3.1 NIFs walk blocks linearly: at each block
// boundary, the file has [uint32 type_name_length][type_name][body]. The
// dispatch table maps the type-name string to a parser function that
// consumes the body and returns a Block variant value. Registration uses
// the NIF_REGISTER_BLOCK macro at static-init time.
//
// "End Of File" is a special sentinel block that closes every BC NIF; it is
// registered with a no-op parser that consumes no body bytes. The walker
// terminates when it encounters this block.
#pragma once

#include <nif/block.h>

#include <functional>
#include <string>
#include <unordered_map>

namespace nif {

class Reader;

using BlockParser = std::function<Block(Reader&)>;

class Dispatch {
public:
    static Dispatch& instance();

    void register_parser(std::string type_name, BlockParser parser);

    /// Returns the parser for `type_name`, or throws UnknownBlockType if
    /// none is registered.
    const BlockParser& get(const std::string& type_name) const;

    bool has(const std::string& type_name) const;

private:
    std::unordered_map<std::string, BlockParser> parsers_;
};

}  // namespace nif

#define NIF_REGISTER_BLOCK(TypeName, ParserFn)                                 \
    namespace { struct _nif_reg_##TypeName {                                    \
        _nif_reg_##TypeName() {                                                 \
            ::nif::Dispatch::instance().register_parser(#TypeName, ParserFn);   \
        }                                                                       \
    } _nif_reg_##TypeName##_instance; }
