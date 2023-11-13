cmake_minimum_required(VERSION 3.25)

project(Dyn VERSION 1.1)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED TRUE)

configure_file(TutorialConfig.h.in TutorialConfig.h)

add_executable(dyn main.cpp)

target_include_directories(dyn PUBLIC "${PROJECT_BINARY_DIR}")
