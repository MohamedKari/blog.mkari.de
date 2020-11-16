hugo-serve:
	hugo serve

pub:
	./publish.sh

web-serve:
	cd public && http-server

go-live:
	git push origin gh-pages