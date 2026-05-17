FROM golang:1.23-alpine AS builder

WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN go build -o /out/auth-service ./cmd/auth-service

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /out/auth-service /app/auth-service

EXPOSE 8080
CMD ["/app/auth-service"]
