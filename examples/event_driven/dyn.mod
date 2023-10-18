dyn 1.0.0 

workspace "eventdriven"
    members (
        "events"
        "subscriber"
        "publisher"
    )
    libdir "./lib"
    require (
        "github.com/17robots/borsh@1.0.0"
    )
    optimize
        debug 2
        release 5

mod "events"
    src "./events/main.dyn"
    require (
        "github.com/17robots/borsh@workspace"
    )
bin "publisher"
    src "./publisher/main.dyn"
    require (
        "github.com/17robots/borsh@workspace"
        "events@workspace"
    )
bin "subscriber"
    src "./subscriber/main.dyn"
    require (
        "github.com/17robots/borsh@workspace"
        "events@workspace"
    )
