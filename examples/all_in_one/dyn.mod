dyn x.x

workspace {  // this is not needed unless a lot of projects share dependencies
  members: [ bin.basic-bin, mod.basic-mod, ] // members is just used to know who gets the workspace dependencies
  dependencies: [ 'http', 'ui', 'somethingelse@x.x.x' ] // shared to all project members
}

bin {
  name: 'basic-bin'
  description: 'A basic binary declaration'
  version: '0.0.0'
  main: 'src/bin/main.dyn'
  dependencies: [
    mod.basic-mod
  ] // any extra dependency not included in the workspace dependencies
}

mod {
  name: 'basic-mod'
  description: 'A basic module declaration'
  version: '0.0.0'
  main: 'src/lib/main.dyn'
  dependencies: [] // any extra dependency not included in the workspace dependencies, not needed if []
}
