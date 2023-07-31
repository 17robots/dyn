from dyn:slim-alpine as builder
workdir /
copy ./dyn.mod .
copy ./subscriber .
run dyn check subscriber
run dyn build subscriber --release

from scratch
copy --from=builder /build/release/subscriber /
cmd /subscriber

