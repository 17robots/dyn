dyn x.x

workspace "example"
  configurations ("debug", "release")
  members (
    "publisher"
    "subscriber"
    "events"
  )
  dependencies (
    "borsh@1.10.3"
    "borsh-derive@0.9.2"
  )
