workspace "eventdriven"
  members (
    "publisher"
    "subscriber"
    "events"
  )
  dependencies (
    "borsh@1.0.0"
    "borsh-derive@1.0.0"
    "crosstown@1.0.0"
  )

configuration:debug
  optimize "2"

configuration:release
  optimize: "5"
