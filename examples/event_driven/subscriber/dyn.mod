project "subscriber"
  type "bin"
  src "./src"
  version "0.1.0"
  author "mdray@ameritech.net"
  dependencies (
    "borsh@workspace"
    "borsh-derive@workspace"
    "crosstown@workspace"
    "events@members"
  )

configuration:debug
  optimize "2"

configuration:release
  optimize: "5"

