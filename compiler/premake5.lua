require'ninja'
workspace'dyn'
    configurations {'Debug', 'Production' }

project'dyn'
    location"./build"
    toolset'clang'
    kind'ConsoleApp'
    language'C++'
    files { 'main.cpp' }
