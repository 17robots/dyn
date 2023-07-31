project "events"
  type "lib"
  src: "./src"
  version "0.1.0"
  author "mdray@ameritech.net"
  dependencies (
    "borsh@workspace"
    "borsh-derive@workspace"
  )

configuration:debug
  optimize "2"

configuration:release
  optimize: "5"
