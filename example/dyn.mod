dyn 1.0.0

bin "starting-over"
    src "./src/main.dyn"
    libdir "./lib" // default
    require (
        "github.com/something/else@1.0" alias
        "github.com/something/else2@1.0"
    )
